from __future__ import annotations

from typing import List
from playwright.async_api import async_playwright
from .models import QACDocument, ModelOption, FormOption, DowntimeOption, CategoryOption


async def _distinct_options(page, selector: str):
    return await page.locator(selector).evaluate_all(
        """els => {
            const seen = new Set();
            const out = [];
            for (const e of els) {
                const value = String(e.value || '').trim();
                const name = String(e.textContent || '').trim();
                if (!value || value === '0' || !name) continue;
                const key = value + '\\u0000' + name;
                if (seen.has(key)) continue;
                seen.add(key);
                out.push({value, name});
            }
            return out;
        }"""
    )


async def scan_documents_async(cdp_url: str) -> List[QACDocument]:
    docs: List[QACDocument] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_url)

        if not browser.contexts:
            raise RuntimeError("ไม่พบ Browser Context")

        context = browser.contexts[0]

        for idx, page in enumerate(context.pages):
            # Robust QAC document detection.
            #
            # Do not depend on which QAC step is currently visible.
            # The operator may be on Task Information, New Time & Event,
            # or an already-created event when Scan is pressed.
            #
            # Primary signal: QAC document URL (measure.html).
            # Secondary DOM signals make the detection safer.
            try:
                url_lower = (page.url or "").lower()
            except Exception:
                url_lower = ""

            is_measure_page = (
                "/app/view/measure.html" in url_lower
                or url_lower.endswith("/measure.html")
                or "measure.html?" in url_lower
            )

            if not is_measure_page:
                # Fallback for environments where URL may be rewritten.
                try:
                    has_task_header = (
                        await page.locator(
                            'h1[data-title][data-line-id]'
                        ).count()
                    ) > 0
                    has_event_form = (
                        await page.locator(
                            'select.dropdown_topic'
                        ).count()
                    ) > 0
                    is_measure_page = has_task_header and has_event_form
                except Exception:
                    is_measure_page = False

            if not is_measure_page:
                continue

            production_date = ""
            line = ""
            shift = ""
            document_no = ""

            try:
                header = page.locator(
                    'h1[data-title][data-line-id]'
                ).first

                production_date = (
                    await header.get_attribute("data-title")
                    or ""
                )

                if not production_date:
                    production_date = (
                        await header.inner_text(timeout=800)
                        or ""
                    ).strip()
            except Exception:
                pass

            async def after_label(label_text: str) -> str:
                try:
                    return await page.evaluate(
                        """(labelText) => {
                            const hs=[...document.querySelectorAll('h5')];
                            const h=hs.find(
                                x => (x.textContent||'').includes(labelText)
                            );
                            if(!h) return '';
                            const n=h.nextElementSibling;
                            return n ? (n.textContent||'').trim() : '';
                        }""",
                        label_text
                    )
                except Exception:
                    return ""

            line = await after_label("Line :")
            shift = await after_label("Shift :")
            document_no = await after_label("Document No :")

            models = []
            try:
                rows = await page.locator(
                    "select.dropdown_model option"
                ).evaluate_all(
                    """els => {
                        const seen = new Set();
                        const out = [];
                        for (const e of els) {
                            const value = String(e.value || '').trim();
                            const name = String(e.textContent || '').trim();
                            const product_number =
                                e.getAttribute('data-product-number') || '';
                            if (!value || value === '0' || !name) continue;
                            const key = value + '\\u0000' + name + '\\u0000' + product_number;
                            if (seen.has(key)) continue;
                            seen.add(key);
                            out.push({value, name, product_number});
                        }
                        return out;
                    }"""
                )
                models = [ModelOption(**row) for row in rows]
            except Exception:
                pass

            machines = []
            try:
                rows = await _distinct_options(
                    page,
                    "select.dropdown_machine option"
                )
                machines = [FormOption(**row) for row in rows]
            except Exception:
                pass

            # Manual Event masters are read directly from the active QAC HTML.
            # Category options are linked to DownTime by option[data-item].
            downtimes = []
            try:
                rows = await page.locator(
                    "select.dropdown_topic option"
                ).evaluate_all(
                    """els => {
                        const seen = new Set();
                        const out = [];
                        for (const e of els) {
                            const value = String(e.value || '').trim();
                            const name = String(e.textContent || '').trim();
                            if (!value || value === '0' || !name) continue;
                            if (seen.has(value)) continue;
                            seen.add(value);
                            out.push({
                                value, name,
                                machine_required: e.getAttribute('data-machine-require') === '1',
                                model_required: e.getAttribute('data-model-require') === '1',
                                production_output_required: e.getAttribute('data-production-output-required') === '1',
                                time_loss_required: e.getAttribute('data-time-loss-required') === '1',
                                category_key: String(e.getAttribute('data-category-item-pcb') || '')
                            });
                        }
                        return out;
                    }"""
                )
                downtimes = [DowntimeOption(**row) for row in rows]
            except Exception:
                pass

            categories = []
            try:
                rows = await page.locator(
                    "select.dropdown_topic_sub option"
                ).evaluate_all(
                    """els => {
                        const seen = new Set();
                        const out = [];
                        for (const e of els) {
                            const value = String(e.value || '').trim();
                            const name = String(e.textContent || '').trim();
                            const downtime_value = String(e.getAttribute('data-item') || '').trim();
                            if (!value || value === '0' || !name || !downtime_value) continue;
                            const key = downtime_value + '\u0000' + value;
                            if (seen.has(key)) continue;
                            seen.add(key);
                            out.push({value, name, downtime_value});
                        }
                        return out;
                    }"""
                )
                categories = [CategoryOption(**row) for row in rows]
            except Exception:
                pass

            ng_products = []
            try:
                rows = await _distinct_options(
                    page,
                    "select.dropdown_ng_type option"
                )
                ng_products = [FormOption(**row) for row in rows]
            except Exception:
                pass

            # I-TAG Production Line Found exists in DOM even while
            # the I-TAG section is hidden.
            itag_lines = []
            try:
                rows = await _distinct_options(
                    page,
                    "select.dropdown_i-tag_process option"
                )
                itag_lines = [FormOption(**row) for row in rows]
            except Exception:
                pass

            # A real QAC document should expose at least Line/Shift/Date.
            # Do not require all three because some QAC versions render fields late.
            identity_score = sum(
                1 for value in (
                    production_date,
                    line,
                    shift,
                    document_no,
                )
                if str(value or "").strip()
            )

            if identity_score < 2:
                continue

            docs.append(
                QACDocument(
                    page_index=idx,
                    title=await page.title(),
                    url=page.url,
                    production_date=production_date,
                    line=line,
                    shift=shift,
                    document_no=document_no,
                    models=models,
                    machines=machines,
                    downtimes=downtimes,
                    categories=categories,
                    ng_products=ng_products,
                    itag_lines=itag_lines,
                )
            )

        return docs



async def load_itag_process_subs_async(
    cdp_url: str,
    page_index: int,
    process_id: str
) -> List[FormOption]:
    """
    Read Process Found from the same QAC service used by the page.
    This is read-only and uses the active QAC session/group.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_url)

        if not browser.contexts:
            raise RuntimeError("ไม่พบ Browser Context")

        pages = browser.contexts[0].pages
        if page_index < 0 or page_index >= len(pages):
            raise RuntimeError("QAC tab ไม่อยู่แล้ว กรุณา Scan ใหม่")

        page = pages[page_index]

        result = await page.evaluate(
            """async (processId) => {
                const groupId = sessionStorage.getItem('qac-itag-group');

                if (!groupId) {
                    return {
                        ok: false,
                        error: 'NO_ITAG_GROUP',
                        items: []
                    };
                }

                const response = await fetch(
                    '../controller/measurementController.asmx/getItagProcessSubService',
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json; charset=utf-8'
                        },
                        body: JSON.stringify({
                            process_id: processId,
                            group_id: groupId
                        })
                    }
                );

                if (!response.ok) {
                    return {
                        ok: false,
                        error: 'HTTP_' + response.status,
                        items: []
                    };
                }

                const data = await response.json();

                return {
                    ok: true,
                    items: (data.d || []).map(x => ({
                        value: String(x.process_sub_id || ''),
                        name: String(x.process_sub_name || '').trim()
                    }))
                };
            }""",
            str(process_id)
        )

        if not result.get("ok"):
            if result.get("error") == "NO_ITAG_GROUP":
                raise RuntimeError(
                    "QAC User นี้ยังไม่มีสิทธิ์/Group ใน I-TAG System"
                )
            raise RuntimeError(
                f"โหลด Process Found ไม่สำเร็จ: {result.get('error')}"
            )

        out = []
        seen = set()

        for row in result.get("items", []):
            value = str(row.get("value", "")).strip()
            name = str(row.get("name", "")).strip()

            if not value or value == "0" or not name:
                continue

            key = (value, name)
            if key in seen:
                continue

            seen.add(key)
            out.append(FormOption(value=value, name=name))

        return out
