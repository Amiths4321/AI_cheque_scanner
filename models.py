from datetime import datetime
from extensions import db


class ChequeRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reference_no = db.Column(db.String(20), unique=True, nullable=False)

    image_filename = db.Column(db.String(200), nullable=True)
    extracted_raw_json = db.Column(db.Text, nullable=True)
    extraction_method = db.Column(db.String(10), default="manual")  # "auto" or "manual"

    bank_name = db.Column(db.String(80))
    branch = db.Column(db.String(80))
    cheque_number = db.Column(db.String(20))
    micr_code = db.Column(db.String(20))
    micr_valid_format = db.Column(db.Boolean, default=False)
    ifsc_code = db.Column(db.String(20))
    ifsc_valid_format = db.Column(db.Boolean, default=False)
    cheque_date = db.Column(db.String(20))

    payee_name = db.Column(db.String(120))
    account_holder_name = db.Column(db.String(120))
    account_number = db.Column(db.String(30))

    amount_words = db.Column(db.String(200))
    amount_figures = db.Column(db.Float)
    amount_words_parsed = db.Column(db.Float)
    amount_match = db.Column(db.Boolean, default=False)

    signature_present = db.Column(db.String(10))  # "Yes" / "No" / "Unclear" — presence only, not verification

    status = db.Column(db.String(20), default="Pending Review")
    scanned_on = db.Column(db.DateTime, default=datetime.utcnow)