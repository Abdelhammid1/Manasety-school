"""AI usage on the console (ticket D): the platform overview (per school,
this month), price cards and the pricing of calls that had no card.
owner: everything · finance: sees cost / price / profit, can't add a card ·
support: tokens and calls only, never an amount."""
from __future__ import annotations

import csv
import io

from flask import Response, abort, flash, redirect, render_template, request, url_for

from . import bp, current_platform_user, require_platform_role
from ...extensions import db
from ...services import platform_ai_usage as pai
from ...services.ai_usage import parse_month
from ...services.school_export import csv_safe

MONEY_ROLES = ("owner", "finance")


@bp.route("/ai-usage", endpoint="ai_usage")
@require_platform_role("owner", "finance", "support")
def ai_usage():
    month_at = parse_month(request.args.get("month"))
    data = pai.overview(current_platform_user(), month_at)
    money = current_platform_user().role in MONEY_ROLES
    if request.args.get("format") == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        head = ["school_id", "school", "calls", "tokens", "unpriced_calls", "monthly_cap", "cap_used_pct",
                "ai_open_without_cap"]
        if money:
            head += ["currency", "cost", "price", "profit"]
        w.writerow(head)
        for r in data["rows"]:
            base = [r["school_id"], csv_safe(r["name"]), r["calls"], r["tokens"], r["unpriced"],
                    r["cap"] if r["cap"] is not None else "", r["percent"] if r["percent"] is not None else "",
                    "yes" if r["open_no_cap"] else ""]
            if money and r["money"]:
                for cur, m in r["money"].items():
                    w.writerow(base + [csv_safe(cur), m["cost"], m["price"], m["profit"]])
            else:
                w.writerow(base + ([""] * 4 if money else []))
        db.session.commit()
        return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition":
                                 f'attachment; filename="ai-usage-{data["start"]:%Y-%m}.csv"'})
    return render_template("superadmin/ai_usage.html", data=data, money=money,
                           month=f"{data['start']:%Y-%m}")


@bp.route("/ai-usage/prices", methods=["GET", "POST"], endpoint="ai_prices")
@require_platform_role(*MONEY_ROLES)
def ai_prices():
    if request.method == "POST":
        if current_platform_user().role != "owner":        # also refused by the route matrix
            abort(403)
        try:
            card = pai.add_card(request.form, current_platform_user())
        except pai.CardError as e:
            db.session.rollback()
            flash(str(e), "danger")
        else:
            db.session.commit()
            flash(f"تمت إضافة بطاقة سعر للموديل {card.model}.", "success")
        return redirect(url_for("superadmin.ai_prices"))
    return render_template("superadmin/ai_prices.html", cards=pai.cards(), fields=pai.CARD_FIELDS,
                           labels=pai.CARD_LABELS)


@bp.route("/ai-usage/price-pending", methods=["POST"], endpoint="ai_price_pending")
@require_platform_role("owner")
def ai_price_pending():
    n = pai.price_pending(current_platform_user())
    db.session.commit()
    flash(f"تم تسعير {n} استدعاء." if n else "لا استدعاءات جديدة لها بطاقة سعر.", "success")
    return redirect(url_for("superadmin.ai_prices"))
