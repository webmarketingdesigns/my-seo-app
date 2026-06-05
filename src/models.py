from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

MONTHLY_CREDITS = 350


class Transaction(db.Model):
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    person = db.Column(db.String(10), nullable=False)  # 'karen' or 'wally'
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(200), nullable=False)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow().date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'person': self.person,
            'amount': self.amount,
            'description': self.description,
            'date': self.date.isoformat(),
            'created_at': self.created_at.isoformat(),
        }
