import os
import calendar
from datetime import datetime, date
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from models import db, Transaction, MONTHLY_CREDITS

app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, '..', 'credits.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-for-credits-app')

db.init_app(app)

with app.app_context():
    db.create_all()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/summary/<year_month>')
def summary(year_month):
    try:
        year, month = map(int, year_month.split('-'))
        first_day = date(year, month, 1)
        days_in_month = calendar.monthrange(year, month)[1]
        last_day = date(year, month, days_in_month)
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid month format, use YYYY-MM'}), 400

    today = date.today()
    days_remaining = max(0, (last_day - today).days + 1) if today.year == year and today.month == month else 0
    days_elapsed = min(today.day, days_in_month) if today.year == year and today.month == month else days_in_month

    result = {}
    for person in ('karen', 'wally'):
        txns = Transaction.query.filter(
            Transaction.person == person,
            Transaction.date >= first_day,
            Transaction.date <= last_day,
        ).all()
        spent = sum(t.amount for t in txns)
        result[person] = {
            'total_credits': MONTHLY_CREDITS,
            'spent': round(spent, 2),
            'remaining': round(MONTHLY_CREDITS - spent, 2),
        }

    result['meta'] = {
        'year': year,
        'month': month,
        'days_in_month': days_in_month,
        'days_elapsed': days_elapsed,
        'days_remaining': days_remaining,
        'month_name': first_day.strftime('%B %Y'),
    }
    return jsonify(result)


@app.route('/api/transactions/<year_month>')
def get_transactions(year_month):
    try:
        year, month = map(int, year_month.split('-'))
        first_day = date(year, month, 1)
        days_in_month = calendar.monthrange(year, month)[1]
        last_day = date(year, month, days_in_month)
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid month format, use YYYY-MM'}), 400

    txns = Transaction.query.filter(
        Transaction.date >= first_day,
        Transaction.date <= last_day,
    ).order_by(Transaction.date.desc(), Transaction.created_at.desc()).all()

    return jsonify([t.to_dict() for t in txns])


@app.route('/api/transactions', methods=['POST'])
def add_transaction():
    data = request.get_json()
    person = (data.get('person') or '').lower().strip()
    if person not in ('karen', 'wally'):
        return jsonify({'error': 'Person must be karen or wally'}), 400

    try:
        amount = float(data.get('amount', 0))
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'error': 'Amount must be a positive number'}), 400

    description = (data.get('description') or '').strip()
    if not description:
        return jsonify({'error': 'Description is required'}), 400

    try:
        txn_date = date.fromisoformat(data.get('date')) if data.get('date') else date.today()
    except ValueError:
        return jsonify({'error': 'Invalid date format, use YYYY-MM-DD'}), 400

    txn = Transaction(person=person, amount=amount, description=description, date=txn_date)
    db.session.add(txn)
    db.session.commit()
    return jsonify(txn.to_dict()), 201


@app.route('/api/transactions/<int:txn_id>', methods=['DELETE'])
def delete_transaction(txn_id):
    txn = Transaction.query.get_or_404(txn_id)
    db.session.delete(txn)
    db.session.commit()
    return jsonify({'deleted': txn_id})
