"""Demo support agent.

Seeds one user with 40 chat messages, derives topic summaries, beliefs, a
profile, and procedures through the SDK, and exposes two tools that read
memory. Then it replays the wrong-employer story:

    python -m demo_agent.support_agent --url http://localhost:8000

Flags: --seed-only to stop after seeding, --no-reset to keep existing data.
"""

import argparse
import sys
from collections import Counter

from demo_agent import recipes as R
from demo_agent.seed_messages import MESSAGES, USER
from rederive import Rederive, exposed

EMAIL = r"([\w.+-]+@[\w-]+(?:\.[\w-]+)+)"
PHONE = r"(\+?\d[\d\s().-]{6,}\d)"

# (key, topic, recipe)
BELIEFS = [
    ("employer", "work", R.fact("employer", "Where does the user work now?",
                                r"work(?:s|ing)? (?:at|for) ([A-Z]\w+)", "User works at {value}.")),
    ("role", "work", R.fact("role", "What is the user's role?", r"I'm an? ([\w ]+?) on", "User is a {value}.")),
    ("manager", "work", R.fact("manager", "Who is the user's manager?", r"manager is (\w+)",
                               "User's manager is {value}.")),
    ("timezone", "work", R.fact("timezone", "What time zone is the user in?", r"on (\w+) time",
                                "User is on {value} time.")),
    ("hours", "work", R.fact("hours", "What are the user's working hours?", r"work from (\d+ to \d+)",
                             "User works from {value}.")),
    ("seats", "work", R.fact("seats", "How many seats does the team have?", r"for (\d+) seats",
                             "Team has {value} seats on the Pro plan.")),
    ("name", "contact", R.fact("name", "What is the user's full name?", r"name is ([A-Z]\w+ [A-Z]\w+)",
                               "User's name is {value}.")),
    ("phone", "contact", R.fact("phone", "What is the user's phone number?", PHONE, "User's phone is {value}.")),
    ("email", "contact", R.fact("email", "What is the user's email?", EMAIL, "User's email is {value}.")),
    ("channel", "contact", R.fact("channel", "Which contact channel does the user prefer?",
                                  r"prefer (\w+) over", "User prefers {value}.")),
    ("quiet_hours", "contact", R.fact("quiet_hours", "When should we not call?", r"before (\d+(?:am|pm))",
                                      "Do not call before {value}.")),
    ("reply_style", "preferences", R.select("reply_style", "List the user's reply style preferences.",
                                            r"short|bullet", "No reply style preference.")),
    ("nickname", "preferences", R.fact("nickname", "What should we call the user?", r"call me (\w+)",
                                       "Address the user as {value}.")),
    ("platforms", "preferences", R.select("platforms", "List the apps the user uses.", r"\bapp\b",
                                          "No known apps.")),
    ("open_orders", "orders", R.select("open_orders", "List orders that still need action.",
                                       r"pending|damaged|replacement", "No open orders.")),
    ("refunds", "orders", R.select("refunds", "List refunds.", r"refund", "No refunds.")),
    ("open_bugs", "issues", R.select("open_bugs", "List unresolved bugs.", r"fails|slow|timed out|error",
                                     "No open bugs.")),
    ("export_bug", "issues", R.select("export_bug", "Summarize the export bug.", r"export",
                                      "No export bug.")),
    ("billing_cycle", "billing", R.fact("billing_cycle", "How often does the user pay?", r"pay (\w+)",
                                        "User pays {value}.")),
    ("renewal", "billing", R.fact("renewal", "When is the renewal?", r"renewal is in (\w+)",
                                  "Renewal is in {value}.")),
    ("billing_email", "billing", R.fact("billing_email", "Where do invoices go?", EMAIL,
                                        "Invoices go to {value}.")),
]

PROFILE_INPUTS = ["name", "employer", "role", "manager", "timezone", "channel", "nickname", "seats",
                  "billing_cycle", "renewal"]

PROCEDURES = [
    ("contact_plan", ["channel", "email", "phone", "quiet_hours", "timezone"],
     R.procedure("contact_plan", "Write how support should contact this user.",
                 {"channel": (r"prefers (\w+)", "email"), "email": (EMAIL, "unknown"),
                  "phone": (r"phone is " + PHONE, "unknown"), "tz": (r"on (\w+) time", "local")},
                 "Contact the user by {channel} at {email}. Schedule for {tz} time. "
                 "For urgent issues, text {phone}.")),
    ("reply_procedure", ["reply_style", "nickname"],
     R.procedure("reply_procedure", "Write how support replies should be styled.",
                 {"name": (r"as (\w+)", "the user")},
                 "Greet {name} by name. Keep replies short and use bullet points.")),
    ("escalation", ["open_bugs", "open_orders"], R.summary("escalation")),
    ("renewal_outreach", ["employer", "manager", "renewal", "seats"],
     R.procedure("renewal_outreach", "Write the renewal outreach plan.",
                 {"renewal": (r"in (\w+)", "the next"), "manager": (r"manager is (\w+)", "the admin"),
                  "employer": (r"works at (\w+)", "the company"), "seats": (r"has (\d+) seats", "all")},
                 "Before the {renewal} renewal, contact {manager} at {employer} about {seats} seats.")),
    ("risk_flags", ["export_bug", "refunds"],
     R.select("risk_flags", "List account risks.", r"twice|blocks|damaged|charged|refund", "No risks.")),
]


class SupportAgent:
    def __init__(self, client: Rederive, k: int = 4):
        self.client = client
        self.k = k
        self.ids: dict[str, dict] = {}

        @exposed(client, name="lookup_profile")
        def lookup_profile() -> str:
            return self.client.read(self.ids["profile"]["id"])["text"]

        @exposed(client, name="draft_reply")
        def draft_reply(question: str) -> str:
            profile = self.client.read(self.ids["profile"]["id"])["text"]
            style = self.client.read(self.ids["reply_procedure"]["id"])["text"]
            renewal = self.client.read(self.ids["renewal_outreach"]["id"])["text"]
            return f"[context] {profile}\n[style] {style}\n[plan] {renewal}\n[question] {question}"

        self.lookup_profile = lookup_profile
        self.draft_reply = draft_reply

    def derive(self, key: str, inputs: list[str], recipe, kind: str) -> dict:
        out = self.client.derive([self.ids[i] for i in inputs], recipe, kind=kind,
                                 fan_in_k=self.k, user=USER, name=key)
        self.ids[key] = out
        return out

    def seed(self) -> dict[str, dict]:
        for topic, msgs in MESSAGES.items():
            for key, text in msgs:
                self.ids[key] = self.client.observe(text, user=USER, topic=topic, name=key)
        for topic, msgs in MESSAGES.items():
            self.derive(f"summary_{topic}", [k for k, _ in msgs], R.summary(topic), "summary")
        for key, topic, recipe in BELIEFS:
            self.derive(key, [f"summary_{topic}"], recipe, "belief")
        self.derive("profile", PROFILE_INPUTS, R.PROFILE, "summary")
        for key, inputs, recipe in PROCEDURES:
            self.derive(key, inputs, recipe, "procedure")
        self.derive("agent_brief", ["profile", "contact_plan", "reply_procedure", "escalation"],
                    R.summary("agent context"), "summary")
        return self.ids


def job_counts(client: Rederive, job_ids: list[int]) -> Counter:
    wanted = set(job_ids)
    return Counter(j["state"] for j in client.jobs()["jobs"] if j["id"] in wanted)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--seed-only", action="store_true")
    parser.add_argument("--no-reset", action="store_true")
    args = parser.parse_args(argv)

    client = Rederive(args.url)
    if not args.no_reset:
        client.reset()
    agent = SupportAgent(client)
    ids = agent.seed()
    graph = client.graph(user=USER)
    kinds = Counter(n["kind"] for n in graph["nodes"])
    print(f"seeded {kinds['observation']} observations and "
          f"{sum(kinds.values()) - kinds['observation']} derived records: {dict(kinds)}")
    print(f"\nprofile v{client.read(ids['profile']['id'])['version']}:\n  "
          + client.read(ids["profile"]["id"])["text"])
    if args.seed_only:
        return 0

    reply = agent.draft_reply("Can we add seats before renewal?")
    call_id = agent.draft_reply.last_call.id
    print(f"\ntool call {call_id} read {len(agent.draft_reply.last_call.reads)} records:\n  "
          + reply.replace("\n", "\n  "))

    print("\nretracting the wrong message: 'I work at Globex.'")
    out = client.retract(ids["m_globex"]["id"])
    print(f"  {out['stale_count']} records went stale")
    client.wait_idle()
    counts = job_counts(client, out["job_ids"])
    print(f"  rebuilt {counts['done']}, stopped by early cutoff {counts['cut_off'] + counts['skipped']} "
          f"(cut_off {counts['cut_off']}, skipped {counts['skipped']}), other {dict(counts)}")

    prof = client.read(ids["profile"]["id"])
    d = client.diff(ids["profile"]["id"], 1, prof["version"])
    print(f"\nprofile diff v1 -> v{prof['version']}:")
    for line in d["unified"][2:]:
        if line.startswith(("+", "-")):
            print(f"  {line}")

    print("\nexposure report (tool calls that read now-invalid versions):")
    for row in client.exposures(stale_only=True):
        print(f"  {row['tool_call_id']} read {row['kind']} v{row['version']} "
              f"({row['state']}, latest v{row['latest_version']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
