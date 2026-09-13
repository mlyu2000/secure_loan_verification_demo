"""Email (SMTP) — approval requests to the senior officer + client notification."""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import settings

log = logging.getLogger("slvd.mail")


def _send(to: str, subject: str, html: str) -> bool:
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = settings.mail_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(settings.mail_host, settings.mail_port, timeout=15) as s:
            s.send_message(msg)
        log.info("mail sent: %s -> %s", subject, to)
        return True
    except Exception as e:  # noqa: BLE001
        log.error("mail failed (%s -> %s): %s", subject, to, e)
        return False


def send_approval_request(request_id: str, case_id: str, emp_id: str,
                          agent: str, tool_host: str, reason: str,
                          approve_8h_link: str, approve_24h_link: str, reject_link: str,
                          dashboard_link: str) -> bool:
    body = f"""
    <h2>Agent Platform &ndash; Access Request</h2>
    <table border="1" cellpadding="6" cellspacing="0">
      <tr><td><b>Request ID</b></td><td>{request_id}</td></tr>
      <tr><td><b>User</b></td><td>{emp_id}</td></tr>
      <tr><td><b>Agent</b></td><td>{agent}</td></tr>
      <tr><td><b>Tool / Host</b></td><td>{tool_host}</td></tr>
      <tr><td><b>Reason</b></td><td>{reason}</td></tr>
    </table>
    <p>The agent requires approval to invoke a governed MCP method for case <b>{case_id}</b>.
    Full context: the analyst requested a loan renewal decision memo that crossed the
    compliance threshold.</p>
    <p>
      <a href="{approve_8h_link}"><b>Approve (8 h)</b></a> &nbsp;
      <a href="{approve_24h_link}"><b>Approve (24 h)</b></a> &nbsp;
      <a href="{reject_link}"><b>Reject</b></a>
    </p>
    <p><a href="{dashboard_link}">View in Admin Dashboard</a></p>
    <p><i>Links expire in 24 hours.</i></p>
    """
    subject = (f"[Agent Platform] Access Request \u2013 {emp_id} \u2192 {tool_host}")
    return _send(settings.approver_email, subject, body)


def send_client_notification(case_id: str, client: str, amount_usd: int, run_id: str) -> bool:
    body = f"""
    <h2 style="color:#16a34a;">Loan Application Approved</h2>
    <p>Good news &mdash; your loan renewal request has been approved.</p>
    <table border="1" cellpadding="6" cellspacing="0">
      <tr><td><b>Case</b></td><td>{case_id}</td></tr>
      <tr><td><b>Client</b></td><td>{client}</td></tr>
      <tr><td><b>Amount</b></td><td>${amount_usd:,}</td></tr>
      <tr><td><b>Run ID</b></td><td>{run_id}</td></tr>
    </table>
    <p>Your dedicated relationship team will follow up with the final documentation.</p>
    """
    return _send(settings.client_email, "Loan Application Approved", body)
