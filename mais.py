# -*- coding: utf-8 -*-
from flask import Blueprint, render_template
from auth import login_required, requer_organizacao

mais_bp = Blueprint("mais", __name__)


@mais_bp.route("/mais")
@login_required
@requer_organizacao
def index():
    return render_template("mais.html")
