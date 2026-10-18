"""Generate the 8 synthetic fraud-compensation cases used for the demo and evals.

Output:
  data/cases.json         - full cases (complaint, events, ground truth) used by the app
  data/bq/cases.jsonl     - case rows for BigQuery
  data/bq/events.jsonl    - event rows for BigQuery

Run:  python data/generate.py
All data is synthetic. Names, accounts and numbers are invented.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
IST = "+05:30"


def ts(day: str, hhmm: str) -> str:
    return f"{day}T{hhmm}:00{IST}"


class CaseBuilder:
    def __init__(self, case_id: str):
        self.case_id = case_id
        self.events: list[dict] = []
        self.n = 0

    def ev(self, day, hhmm, etype, source, summary, **attrs):
        self.n += 1
        eid = f"{self.case_id}-E{self.n:02d}"
        self.events.append({
            "event_id": eid, "case_id": self.case_id, "ts": ts(day, hhmm),
            "type": etype, "source": source, "summary": summary, "attrs": attrs,
        })
        return eid


def case_1():
    b = CaseBuilder("C1001")
    b.ev("2027-02-02", "09:10", "LOGIN", "netbanking", "Routine login from registered phone", device_id="D-REG-11", new_device=False, ip_city="Pune")
    b.ev("2027-02-03", "22:41", "SIM_SWAP", "telecom", "SIM replaced at a telecom retail store; customer did not request it", initiated_by="telecom_store", customer_requested=False)
    b.ev("2027-02-03", "22:58", "DEVICE_BIND", "mobile_app", "New device bound to the account", device_id="D-NEW-77", new_device=True)
    b.ev("2027-02-03", "23:01", "OTP_SENT", "otp_gateway", "OTP sent to registered number (now on the swapped SIM)", purpose="device_bind")
    b.ev("2027-02-03", "23:05", "AUTH", "upi", "UPI PIN reset and transaction authorised from the new device", txn_id="T1", device_id="D-NEW-77", method="otp+upi_pin")
    b.ev("2027-02-03", "23:06", "TXN", "upi", "UPI transfer to an unknown beneficiary", txn_id="T1", amount=40000, disputed=True, device_id="D-NEW-77", beneficiary="mule-acct-4412")
    b.ev("2027-02-03", "23:06", "BANK_ALERT", "sms", "Debit alert sent to registered number (on swapped SIM, not received by customer)", delivered=True, to_customer=False)
    b.ev("2027-02-04", "10:20", "COMPLAINT_BANK", "branch", "Customer reports fraud at branch", reported=True)
    b.ev("2027-02-04", "10:45", "COMPLAINT_1930", "ncrp", "Complaint filed on cybercrime.gov.in", ack="NCRP-27-118842")
    return {
        "case_id": "C1001", "customer": "Priya Sharma", "account_type": "individual", "segment": "Savings",
        "received_on": "2027-02-04", "as_of": "2027-02-06", "cross_border": False, "prior_compensation": False,
        "complaint_text": (
            "On the night of 3 Feb my phone suddenly lost network. Next morning I saw Rs 40,000 had gone from my account "
            "by UPI to someone I do not know. I never shared any OTP or PIN with anyone. The telecom store says my SIM was "
            "replaced on 3 Feb but I did not go there. I have also filed a complaint on the cybercrime portal, ref NCRP-27-118842."
        ),
        "events": b.events,
        "expected": {"classification": "THIRD_PARTY_BREACH", "outcome": "ZERO_LIABILITY_REFUND", "bank_pays": 40000, "compensation": 0},
        "story": "SIM swap by a telecom store, new device, reported next day",
    }


def case_2():
    b = CaseBuilder("C1002")
    b.ev("2027-02-10", "11:02", "CALL_REPORTED", "complaint", "Customer received a call from a person claiming to be bank staff", caller="+91-9xxxx-21877")
    b.ev("2027-02-10", "11:05", "OTP_SENT", "otp_gateway", "OTP sent to registered number for beneficiary addition", purpose="add_beneficiary")
    b.ev("2027-02-10", "11:06", "AUTH", "netbanking", "Beneficiary added and transfer authorised with OTP", txn_id="T1", device_id="D-UNK-09", method="otp")
    b.ev("2027-02-10", "11:07", "TXN", "imps", "IMPS transfer to newly added beneficiary", txn_id="T1", amount=30000, disputed=True, device_id="D-UNK-09")
    b.ev("2027-02-10", "11:07", "BANK_ALERT", "sms", "Debit alert delivered to customer", delivered=True, to_customer=True)
    b.ev("2027-02-10", "11:40", "COMPLAINT_1930", "helpline", "Customer called 1930", ack="1930-27-552190")
    b.ev("2027-02-10", "12:15", "COMPLAINT_BANK", "phone_banking", "Customer reports fraud to bank", reported=True)
    b.ev("2027-02-14", "16:00", "RECOVERY", "lien", "Amount recovered from beneficiary account via lien", amount=10000)
    return {
        "case_id": "C1002", "customer": "Ramesh Iyer", "account_type": "individual", "segment": "Savings",
        "received_on": "2027-02-10", "as_of": "2027-02-15", "cross_border": False, "prior_compensation": False,
        "complaint_text": (
            "A man called saying he was from the bank KYC team and my account would be blocked. He asked me to read out "
            "the OTP I received, and I did. Rs 30,000 was transferred out. I called 1930 at once (ref 1930-27-552190) and "
            "then the bank. I was told Rs 10,000 has been frozen and returned."
        ),
        "events": b.events,
        "expected": {"classification": "CUSTOMER_NEGLIGENCE", "outcome": "COMPENSATION", "bank_pays": 0, "compensation": 17000},
        "story": "Customer read out OTP to a fake KYC caller; partial recovery",
    }


def case_3():
    b = CaseBuilder("C1003")
    b.ev("2027-01-28", "08:00", "BREACH_ADVISORY", "payment_aggregator", "Payment aggregator notifies card data exposure affecting merchant checkouts", party="PayFlux PA", card_bins=["512345"])
    b.ev("2027-02-01", "02:14", "TXN", "card_cnp", "Online card purchase at overseas merchant", txn_id="T1", amount=18000, disputed=True, device_id=None, merchant="eStore-LT")
    b.ev("2027-02-01", "02:14", "AUTH", "card_cnp", "Authorised with card details (exempted low-risk flow)", txn_id="T1", method="card_details")
    b.ev("2027-02-01", "02:31", "TXN", "card_cnp", "Second online card purchase", txn_id="T2", amount=12000, disputed=True, device_id=None, merchant="eStore-LT")
    b.ev("2027-02-01", "02:31", "AUTH", "card_cnp", "Authorised with card details", txn_id="T2", method="card_details")
    b.ev("2027-02-01", "02:32", "BANK_ALERT", "email", "Debit alerts emailed to customer", delivered=True, to_customer=True)
    b.ev("2027-02-08", "13:30", "COMPLAINT_BANK", "app", "Customer raises dispute in app", reported=True)
    b.ev("2027-02-08", "14:00", "COMPLAINT_1930", "ncrp", "NCRP complaint filed", ack="NCRP-27-120771")
    return {
        "case_id": "C1003", "customer": "Ananya Rao", "account_type": "individual", "segment": "Credit card",
        "received_on": "2027-02-08", "as_of": "2027-02-09", "cross_border": False, "prior_compensation": False,
        "complaint_text": (
            "I noticed two online purchases of Rs 18,000 and Rs 12,000 on my card from 1 Feb which I did not make. "
            "I was travelling and only checked my email on 8 Feb. I have never shared my card details."
        ),
        "events": b.events,
        "expected": {"classification": "THIRD_PARTY_BREACH", "outcome": "BANK_POLICY_REVIEW", "bank_pays": None, "compensation": 0},
        "story": "Card data leaked at a payment aggregator; reported on day 7",
    }


def case_4():
    b = CaseBuilder("C1004")
    b.ev("2027-02-15", "19:20", "APP_INSTALL", "device_telemetry", "Screen-sharing app installed on registered phone after a 'trading tips' chat", app="QuickSupport-Pro", risk="remote_access")
    b.ev("2027-02-15", "19:22", "SCAM_WARNING", "mobile_app", "Bank app showed a warning: remote access app detected, do not proceed", acknowledged=True)
    b.ev("2027-02-15", "19:30", "AUTH", "mobile_app", "Transfer authorised on registered device during screen share", txn_id="T1", device_id="D-REG-31", method="mpin")
    b.ev("2027-02-15", "19:31", "TXN", "imps", "IMPS transfer to 'investment desk'", txn_id="T1", amount=50000, disputed=True, device_id="D-REG-31")
    b.ev("2027-02-15", "19:44", "AUTH", "mobile_app", "Second transfer authorised", txn_id="T2", device_id="D-REG-31", method="mpin")
    b.ev("2027-02-15", "19:45", "TXN", "imps", "Second IMPS transfer", txn_id="T2", amount=30000, disputed=True, device_id="D-REG-31")
    b.ev("2027-02-15", "21:10", "COMPLAINT_BANK", "phone_banking", "Customer reports fraud", reported=True)
    b.ev("2027-02-15", "21:30", "COMPLAINT_1930", "helpline", "1930 complaint", ack="1930-27-560032")
    b.ev("2027-02-15", "21:52", "AUTH", "mobile_app", "Transaction authorised after the account was reported", txn_id="T3", device_id="D-REG-31", method="mpin")
    b.ev("2027-02-15", "21:53", "TXN", "upi", "UPI transfer after fraud was reported (account not yet blocked)", txn_id="T3", amount=10000, disputed=True, device_id="D-REG-31")
    return {
        "case_id": "C1004", "customer": "Vikram Mehta", "account_type": "individual", "segment": "Savings",
        "received_on": "2027-02-15", "as_of": "2027-02-17", "cross_border": False, "prior_compensation": False,
        "complaint_text": (
            "I joined a stock tips group and they asked me to install an app so they could guide me. While the app was on "
            "they moved Rs 50,000 and Rs 30,000 from my account. I called the bank at 9:10 pm and 1930, but another "
            "Rs 10,000 went at 9:53 pm even after I reported it."
        ),
        "events": b.events,
        "expected": {"classification": "CUSTOMER_NEGLIGENCE", "outcome": "CUSTOMER_LIABLE", "bank_pays": 10000, "compensation": 0},
        "story": "Remote-access app scam, warning ignored, Rs 80k before reporting plus Rs 10k after",
    }


def case_5():
    b = CaseBuilder("C1005")
    b.ev("2027-01-20", "12:00", "CONTACT_UPDATE", "branch", "Customer requested mobile number change at branch; request not processed by bank", processed=False, bank_fault=True)
    b.ev("2027-02-01", "15:12", "OTP_SENT", "otp_gateway", "OTP sent to the OLD mobile number still on record (number since reassigned)", purpose="login", bank_fault=True)
    b.ev("2027-02-01", "15:14", "LOGIN", "netbanking", "Login from unknown device", device_id="D-UNK-55", new_device=True, ip_city="Jamtara")
    b.ev("2027-02-01", "15:16", "AUTH", "netbanking", "Transfer authorised with OTP sent to old number", txn_id="T1", device_id="D-UNK-55", method="otp")
    b.ev("2027-02-01", "15:17", "TXN", "neft", "NEFT transfer", txn_id="T1", amount=15000, disputed=True, device_id="D-UNK-55")
    b.ev("2027-02-01", "15:17", "BANK_ALERT", "sms", "Debit alert sent to old number; customer never received it", delivered=True, to_customer=False)
    b.ev("2027-02-10", "11:00", "COMPLAINT_BANK", "branch", "Customer reports after seeing statement", reported=True)
    b.ev("2027-02-10", "11:30", "COMPLAINT_1930", "ncrp", "NCRP complaint", ack="NCRP-27-123300")
    return {
        "case_id": "C1005", "customer": "Fatima Khan", "account_type": "individual", "segment": "Savings",
        "received_on": "2027-02-10", "as_of": "2027-02-11", "cross_border": False, "prior_compensation": False,
        "complaint_text": (
            "I gave a written request on 20 Jan to change my mobile number. I found in my statement that Rs 15,000 was "
            "sent by NEFT on 1 Feb. I never got any OTP or SMS because the bank was still using my old number."
        ),
        "events": b.events,
        "expected": {"classification": "BANK_NEGLIGENCE", "outcome": "ZERO_LIABILITY_REFUND", "bank_pays": 15000, "compensation": 0},
        "story": "Bank failed to update mobile number; OTP went to reassigned old number; reported day 9",
    }


def case_6():
    b = CaseBuilder("C1006")
    b.ev("2027-02-18", "20:01", "DEVICE_BIND", "mobile_app", "New device bound after OTP", device_id="D-NEW-63", new_device=True)
    b.ev("2027-02-18", "20:00", "OTP_SENT", "otp_gateway", "OTP sent to registered number", purpose="device_bind")
    b.ev("2027-02-18", "20:05", "AUTH", "upi", "First transaction authorised from new device", txn_id="T1", device_id="D-NEW-63", method="upi_pin")
    b.ev("2027-02-18", "20:06", "TXN", "upi", "UPI transfer", txn_id="T1", amount=20000, disputed=True, device_id="D-NEW-63")
    b.ev("2027-02-18", "20:12", "TXN", "upi", "Second UPI transfer (no authentication record found)", txn_id="T2", amount=15000, disputed=True, device_id="D-NEW-63")
    b.ev("2027-02-19", "09:15", "COMPLAINT_BANK", "app", "Customer reports fraud", reported=True)
    b.ev("2027-02-19", "09:40", "COMPLAINT_1930", "helpline", "1930 complaint", ack="1930-27-571145")
    return {
        "case_id": "C1006", "customer": "Arjun Nair", "account_type": "individual", "segment": "Savings",
        "received_on": "2027-02-19", "as_of": "2027-02-20", "cross_border": False, "prior_compensation": False,
        "complaint_text": (
            "Rs 20,000 and Rs 15,000 went out by UPI on the evening of 18 Feb. I did not do these and did not share any OTP. "
            "I reported to 1930 and the bank the next morning."
        ),
        "events": b.events,
        "expected": {"classification": "UNDETERMINED", "outcome": "INCOMPLETE_EVIDENCE", "bank_pays": None, "compensation": 0},
        "story": "New device bound; auth log missing for the second transaction",
    }


def case_7():
    b = CaseBuilder("C1007")
    b.ev("2027-02-21", "17:30", "PHISHING_SMS", "complaint", "Customer clicked an SMS link about an electricity bill and entered card OTP on the page", link="bses-pay-update.in")
    b.ev("2027-02-21", "17:33", "AUTH", "card_cnp", "Transaction authorised with OTP entered on phishing page", txn_id="T1", method="otp")
    b.ev("2027-02-21", "17:34", "TXN", "card_cnp", "Card-not-present purchase", txn_id="T1", amount=25000, disputed=True, device_id=None)
    b.ev("2027-02-22", "10:00", "COMPLAINT_BANK", "app", "Customer reports fraud to bank", reported=True)
    return {
        "case_id": "C1007", "customer": "Meera Joshi", "account_type": "individual", "segment": "Debit card",
        "received_on": "2027-02-22", "as_of": "2027-02-23", "cross_border": False, "prior_compensation": False,
        "complaint_text": (
            "I got an SMS saying my electricity would be cut. I opened the link and paid, and entered the OTP. Later Rs 25,000 "
            "was charged instead. I am reporting this to the bank. I have not filed any police or cyber complaint yet."
        ),
        "events": b.events,
        "expected": {"classification": "CUSTOMER_NEGLIGENCE", "outcome": "PENDING_CUSTOMER_ACTION", "bank_pays": 0, "compensation": 21250},
        "story": "Phishing link, OTP entered; reported to bank but not to 1930 yet",
    }


def case_8():
    b = CaseBuilder("C1008")
    b.ev("2026-11-04", "10:00", "DEVICE_BIND", "mobile_app", "Device registered 3 months earlier", device_id="D-REG-08", new_device=False)
    b.ev("2027-02-12", "13:20", "LOGIN", "mobile_app", "Login from registered device, usual city", device_id="D-REG-08", new_device=False, ip_city="Bengaluru")
    b.ev("2027-02-12", "13:24", "LIVENESS", "kyc_engine", "Face liveness check passed for high-value step-up", result="pass", score=0.97)
    b.ev("2027-02-12", "13:25", "AUTH", "mobile_app", "Purchase authorised with biometric on registered device", txn_id="T1", device_id="D-REG-08", method="biometric")
    b.ev("2027-02-12", "13:25", "TXN", "upi", "Payment to an electronics merchant the customer paid twice before", txn_id="T1", amount=12000, disputed=True, device_id="D-REG-08", merchant="TechKart")
    b.ev("2027-02-12", "13:25", "BANK_ALERT", "sms", "Debit alert delivered", delivered=True, to_customer=True)
    b.ev("2027-02-13", "09:00", "COMPLAINT_BANK", "app", "Customer disputes transaction", reported=True)
    b.ev("2027-02-13", "09:20", "COMPLAINT_1930", "ncrp", "NCRP complaint", ack="NCRP-27-121907")
    return {
        "case_id": "C1008", "customer": "Rohit Verma", "account_type": "individual", "segment": "Savings",
        "received_on": "2027-02-13", "as_of": "2027-02-14", "cross_border": False, "prior_compensation": False,
        "complaint_text": (
            "There is a Rs 12,000 payment to TechKart on 12 Feb which I do not recognise. Please reverse it."
        ),
        "events": b.events,
        "expected": {"classification": "NOT_FRAUD", "outcome": "REJECT_NOT_FRAUD", "bank_pays": 0, "compensation": 0},
        "story": "Registered device, biometric, liveness passed, known merchant",
    }


def main():
    cases = [case_1(), case_2(), case_3(), case_4(), case_5(), case_6(), case_7(), case_8()]
    for c in cases:
        c["events"].sort(key=lambda e: e["ts"])
    (HERE / "cases.json").write_text(json.dumps(cases, indent=2, ensure_ascii=False), encoding="utf-8")
    bq = HERE / "bq"
    bq.mkdir(exist_ok=True)
    with open(bq / "cases.jsonl", "w", encoding="utf-8") as f:
        for c in cases:
            row = {k: v for k, v in c.items() if k not in ("events",)}
            row["expected"] = json.dumps(row["expected"])
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(bq / "events.jsonl", "w", encoding="utf-8") as f:
        for c in cases:
            for e in c["events"]:
                row = dict(e)
                row["attrs"] = json.dumps(e["attrs"])
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(cases)} cases, {sum(len(c['events']) for c in cases)} events")


if __name__ == "__main__":
    main()
