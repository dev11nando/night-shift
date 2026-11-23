from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from night_shift.adapters.storage.models import Company, Outreach, utcnow
from night_shift.domain.enums import OutreachStatus

RECONTACT_DAYS = 60
RECHECK_DAYS = 30

# Ordem de prioridade para escolher quem recebe mensagem primeiro.
SECTOR_PRIORITY = {"fintech": 0, "banco_digital": 1, "ia": 2, "fundo": 3, "tech": 4}


class OutreachRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    # ---------------------------------------------------------------- descoberta

    def needing_discovery(self, limit: int = 1000) -> Sequence[Company]:
        """Empresas com site, nunca varridas ou varridas há mais de 30 dias."""
        cutoff = utcnow() - timedelta(days=RECHECK_DAYS)
        return self.s.scalars(
            select(Company)
            .where(
                Company.website.is_not(None),
                or_(Company.contact_checked_at.is_(None), Company.contact_checked_at < cutoff),
            )
            .order_by(Company.name)
            .limit(limit)
        ).all()

    def save_discovery(self, company: Company, contact, source_url, careers_url, about) -> None:
        # Contato do YAML (manual) nunca é trocado pelo descoberto.
        manual = company.contact_source_url == "config/companies.yaml"
        if contact and not manual:
            company.outreach_contact, company.contact_source_url = contact, source_url
        company.careers_url = careers_url or company.careers_url
        company.about = about or company.about
        company.contact_checked_at = utcnow()

    # ------------------------------------------------------------------ mensagens

    def generated_today(self) -> int:
        today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        return self.s.scalar(select(func.count(Outreach.id)).where(Outreach.created_at >= today))

    def candidates(self, limit: int) -> list[Company]:
        """Empresas sem mensagem pendente e sem contato nos últimos 60 dias. Primeiro as que
        têm e-mail, depois por setor e as que têm descrição (mensagem mais específica)."""
        cutoff = utcnow() - timedelta(days=RECONTACT_DAYS)
        busy = select(Outreach.company_id).where(
            or_(
                Outreach.status == OutreachStatus.DRAFT,
                (Outreach.status.in_([OutreachStatus.SENT, OutreachStatus.REPLIED]))
                & (Outreach.sent_at >= cutoff),
            )
        )
        # Comparação de data no SQL: o SQLite devolve datetime sem fuso.
        rows = list(
            self.s.scalars(
                select(Company).where(
                    Company.id.not_in(busy),
                    or_(Company.last_contacted_at.is_(None), Company.last_contacted_at < cutoff),
                )
            ).all()
        )
        rows.sort(
            key=lambda c: (
                c.outreach_contact is None,
                SECTOR_PRIORITY.get(c.sector or "", 9),
                c.about is None,
                c.name,
            )
        )
        return rows[:limit]

    def save_message(self, company: Company, msg) -> Outreach:
        row = Outreach(
            company_id=company.id,
            to_address=company.outreach_contact,
            subject=msg.subject,
            body=msg.email_body,
        )
        self.s.add(row)
        self.s.flush()
        return row

    def by_status(self, *statuses: OutreachStatus, limit: int = 200) -> Sequence[Outreach]:
        return self.s.scalars(
            select(Outreach)
            .where(Outreach.status.in_(statuses))
            .order_by(Outreach.created_at.desc())
            .limit(limit)
        ).all()

    def counts(self) -> dict[str, int]:
        rows = self.s.execute(select(Outreach.status, func.count()).group_by(Outreach.status)).all()
        return {str(status): n for status, n in rows}

    def set_status(self, outreach_id: int, status: OutreachStatus) -> Outreach:
        row = self.s.get_one(Outreach, outreach_id)
        row.status = status
        if status is OutreachStatus.SENT:
            row.sent_at = utcnow()
            row.company.last_contacted_at = row.sent_at
        elif status is OutreachStatus.DRAFT:  # desfazer "enviado"
            row.sent_at = None
            row.company.last_contacted_at = None
        self.s.flush()
        return row
