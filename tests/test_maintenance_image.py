"""maintenance_image.py 单元测试"""

import io

from reportlab.pdfgen import canvas as canvas_mod

from epson_keeper.maintenance_image import draw_maintenance_page, PAGE_W, PAGE_H


class TestDrawMaintenancePage:
    def test_runs_without_error(self):
        buf = io.BytesIO()
        cv = canvas_mod.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
        draw_maintenance_page(cv)
        cv.save()
        assert buf.tell() > 0

    def test_custom_dimensions(self):
        buf = io.BytesIO()
        cv = canvas_mod.Canvas(buf, pagesize=(400, 600))
        draw_maintenance_page(cv, width=400, height=600)
        cv.save()
        assert buf.tell() > 0
