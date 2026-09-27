"""Forty support-chat messages from one user, grouped by topic.

One message is wrong: "I work at Globex." came from a transcript where Dana
was talking about a vendor, not her employer. The agent stored it anyway.
"""

USER = "dana"

MESSAGES: dict[str, list[tuple[str, str]]] = {
    "work": [
        ("m_role", "I'm a data engineer on the platform team."),
        ("m_initech", "I started working at Initech in March."),
        ("m_manager", "My manager is Priya."),
        ("m_globex", "I work at Globex."),  # wrong
        ("m_tz", "I am on Central time."),
        ("m_hours", "I usually work from 9 to 5."),
        ("m_seats", "Our team uses the Pro plan for 12 seats."),
    ],
    "contact": [
        ("m_name", "My name is Dana Lee."),
        ("m_phone", "My phone number is 512-555-0199."),
        ("m_email", "Email me at dana@example.com."),
        ("m_channel", "I prefer email over phone calls."),
        ("m_no_early", "Please do not call before 10am."),
        ("m_text", "You can text me if something is urgent."),
    ],
    "preferences": [
        ("m_short", "I prefer short replies."),
        ("m_bullets", "I like bullet points."),
        ("m_nick", "Please call me Dana."),
        ("m_android", "I use the Android app."),
        ("m_web", "I also use the web app."),
        ("m_dark", "I use dark mode."),
        ("m_evening", "I read replies in the evening."),
    ],
    "orders": [
        ("m_o1142", "Order 1142 shipped on May 3."),
        ("m_o1150", "Order 1150 is still pending."),
        ("m_refund_ask", "I asked for a refund on order 1142."),
        ("m_refund_card", "The refund for order 1142 went to my card."),
        ("m_o1163", "Order 1163 arrived damaged."),
        ("m_replace", "I want a replacement for order 1163."),
        ("m_ship_to", "Ship replacements to the Austin office."),
    ],
    "issues": [
        ("m_export", "The export button fails on Android."),
        ("m_sync", "Sync is slow on the web app."),
        ("m_twice", "I reported the export bug twice."),
        ("m_login", "The login page timed out yesterday."),
        ("m_blocks", "The export bug blocks my weekly report."),
        ("m_faster", "Sync got faster after the update."),
        ("m_e42", "I see error E42 when exporting."),
    ],
    "billing": [
        ("m_yearly", "We pay yearly."),
        ("m_invoices", "Invoices go to billing@initech.example."),
        ("m_renewal", "Our renewal is in September."),
        ("m_double", "I got charged twice in April."),
        ("m_refunded", "The double charge was refunded."),
        ("m_more_seats", "We might add 3 more seats."),
    ],
}

assert sum(len(v) for v in MESSAGES.values()) == 40
