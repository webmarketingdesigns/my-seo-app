"""Shared request helpers."""
from flask import abort, request

from ..models import Brand


def current_brand():
    """The brand in scope for this request (?brand=<id>, else the first one)."""
    brand_id = request.args.get('brand', type=int) or request.form.get('brand', type=int)
    if brand_id:
        brand = Brand.query.get(brand_id)
        if brand is None:
            abort(404, description='Brand not found')
        return brand
    return Brand.query.order_by(Brand.id).first()


def all_brands():
    return Brand.query.order_by(Brand.name).all()


def payload() -> dict:
    """Body of a JSON or form request, whichever the client sent."""
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form.to_dict()
