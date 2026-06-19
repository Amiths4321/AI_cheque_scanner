import os
import random
import string
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename

from config import Config
from extensions import db
from models import ChequeRecord
from cheque_extract import extract_cheque, words_to_number, clean_amount_figures, validate_ifsc, validate_micr

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

with app.app_context():
    db.create_all()
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]


def generate_reference_no():
    return "CHQ" + datetime.now().strftime("%y%m%d") + "".join(random.choices(string.digits, k=4))


@app.route("/")
def home():
    return render_template("home.html")


# ---------- Upload & scan ----------
@app.route("/scan", methods=["GET", "POST"])
def scan():
    if request.method == "POST":
        doc_file = request.files.get("cheque_image")

        if not doc_file or not doc_file.filename or not allowed_file(doc_file.filename):
            flash("Please upload a valid image file (png, jpg, jpeg).")
            return redirect(url_for("scan"))

        fname = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{doc_file.filename}")
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], fname)
        doc_file.save(save_path)

        success, data, raw_text, error_message = extract_cheque(
            save_path, app.config["OLLAMA_HOST"], app.config["OLLAMA_MODEL"],
            app.config["OLLAMA_TIMEOUT_SECONDS"],
        )

        session["image_filename"] = fname

        if success:
            session["extraction_method"] = "auto"
            session["extracted_raw_json"] = raw_text
            for key in ["bank_name", "branch", "cheque_number", "micr_code", "ifsc_code", "date",
                        "payee_name", "account_holder_name", "account_number", "amount_words",
                        "signature_present"]:
                session[key] = data.get(key) or ""
            session["amount_figures"] = str(data.get("amount_figures") or "")
            flash("Cheque scanned successfully. Please review the details below.")
        else:
            session["extraction_method"] = "manual"
            session["extracted_raw_json"] = ""
            for key in ["bank_name", "branch", "cheque_number", "micr_code", "ifsc_code", "date",
                        "payee_name", "account_holder_name", "account_number", "amount_words",
                        "amount_figures", "signature_present"]:
                session[key] = ""
            flash(f"Auto-scan couldn't complete ({error_message}). Please enter the details manually below.")

        return redirect(url_for("review"))

    return render_template("scan.html")


# ---------- Review, cross-check, and save ----------
@app.route("/review", methods=["GET", "POST"])
def review():
    if "image_filename" not in session:
        return redirect(url_for("scan"))

    if request.method == "POST":
        amount_figures = clean_amount_figures(request.form.get("amount_figures"))
        amount_words_parsed = words_to_number(request.form.get("amount_words"))
        amount_match = (
            amount_figures is not None and amount_words_parsed is not None
            and abs(amount_figures - amount_words_parsed) < 0.01
        )

        ifsc_code = request.form.get("ifsc_code", "").strip().upper()
        micr_code = request.form.get("micr_code", "").strip()

        record = ChequeRecord(
            reference_no=generate_reference_no(),
            image_filename=session.get("image_filename"),
            extracted_raw_json=session.get("extracted_raw_json"),
            extraction_method=session.get("extraction_method", "manual"),
            bank_name=request.form.get("bank_name"),
            branch=request.form.get("branch"),
            cheque_number=request.form.get("cheque_number"),
            micr_code=micr_code,
            micr_valid_format=validate_micr(micr_code),
            ifsc_code=ifsc_code,
            ifsc_valid_format=validate_ifsc(ifsc_code),
            cheque_date=request.form.get("date"),
            payee_name=request.form.get("payee_name"),
            account_holder_name=request.form.get("account_holder_name"),
            account_number=request.form.get("account_number"),
            amount_words=request.form.get("amount_words"),
            amount_figures=amount_figures,
            amount_words_parsed=amount_words_parsed,
            amount_match=amount_match,
            signature_present=request.form.get("signature_present") or "Unclear",
        )
        db.session.add(record)
        db.session.commit()

        for key in ["image_filename", "extraction_method", "extracted_raw_json", "bank_name", "branch",
                    "cheque_number", "micr_code", "ifsc_code", "date", "payee_name",
                    "account_holder_name", "account_number", "amount_words", "amount_figures",
                    "signature_present"]:
            session.pop(key, None)

        return redirect(url_for("confirmation", ref=record.reference_no))

    return render_template("review.html", data=session)


@app.route("/confirmation")
def confirmation():
    ref = request.args.get("ref")
    record = ChequeRecord.query.filter_by(reference_no=ref).first()
    return render_template("confirmation.html", record=record)


# ---------- Register (list of all scanned cheques) ----------
@app.route("/register")
def register():
    records = ChequeRecord.query.order_by(ChequeRecord.scanned_on.desc()).all()
    return render_template("register.html", records=records)


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False, host="0.0.0.0", port=5003)