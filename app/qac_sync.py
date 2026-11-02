from __future__ import annotations

from datetime import datetime
from typing import Callable

from .qac_cache import (
    QacCache,
    build_document_key,
)


async def read_document_identity(page) -> dict:
    """Read real QAC document labels, including the Measure view.

    Missing identity is never interpreted as a match by writers.
    """
    result = await page.evaluate(r"""() => {
        const clean=s=>String(s||'').replace(/\s+/g,' ').trim();
        const labels=[...document.querySelectorAll('h5')];
        const find=(pattern)=>{
            for(const label of labels){
                if(pattern.test(clean(label.textContent))){
                    const next=label.nextElementSibling;
                    if(next) return clean(next.textContent);
                }
            }
            return '';
        };
        const dateHeader=document.querySelector('h1[data-title][data-line-id]');
        return {
            production_date: find(/^Production date\s*[:.]?$/i) || (dateHeader ? clean(dateHeader.getAttribute('data-title') || dateHeader.textContent):''),
            line: find(/^Line\s*[:.]?$/i),
            shift: find(/^Shift\s*[:.]?$/i),
            document_no: find(/^Document No\s*[:.]?$/i),
            document_name: find(/^Document name\s*[:.]?$/i),
            url: String(location.href||'')
        };
    }""")
    return {key: str(result.get(key, '') or '').strip() for key in (
        'production_date','line','shift','document_no','document_name','url')}


async def timeline_result_ids(
    page
) -> list[str]:
    return await page.locator(
        ".f1-step[data-result]"
    ).evaluate_all(
        """els => [...new Set(
            els.map(
                e => String(
                    e.getAttribute('data-result')
                    || ''
                ).trim()
            ).filter(
                v => v && v !== '0'
            )
        )]"""
    )


async def visible_form_events(
    page
) -> list[dict]:
    return await page.evaluate(
        """() => {
            const roots=[
                ...document.querySelectorAll(
                    '.task-downtime[data-result-id], ' +
                    '.fieldset.task-downtime[data-result-id]'
                )
            ];

            const seen=new Set();
            const out=[];

            const val=(r,s)=>{
                const e=r.querySelector(s);
                return e
                    ? String(e.value||'').trim()
                    : '';
            };

            const text=(r,s)=>{
                const e=r.querySelector(s);
                if(!e) return '';
                const o=e.options
                    ? e.options[e.selectedIndex]
                    : null;
                return String(
                    o ? o.textContent : ''
                ).trim();
            };

            const actualQty=(r)=>{
                const inputs=[
                    ...r.querySelectorAll('input')
                ];

                for(const el of inputs){
                    const meta=(
                        String(el.name||'')+' '+
                        String(el.id||'')+' '+
                        String(el.className||'')
                    ).toLowerCase();

                    if(meta.includes('actual')){
                        return String(
                            el.value||''
                        ).trim();
                    }

                    const p=el.closest(
                        '.form-group,.row,[class*="col-"]'
                    );

                    const t=String(
                        p ? p.innerText : ''
                    ).toLowerCase();

                    if(
                        t.includes('actual (qty)') ||
                        t.includes('จำนวนชิ้นงานจริง')
                    ){
                        return String(
                            el.value||''
                        ).trim();
                    }
                }

                return '';
            };

            for(const r of roots){
                const id=String(
                    r.getAttribute(
                        'data-result-id'
                    )||''
                ).trim();

                if(
                    !id
                    || id==='0'
                    || seen.has(id)
                ){
                    continue;
                }

                seen.add(id);

                out.push({
                    source:'form',
                    result_id:id,
                    topic_value:
                        val(r,'select.dropdown_topic'),
                    topic_label:
                        text(r,'select.dropdown_topic'),
                    category_value:
                        val(r,'select.dropdown_topic_sub'),
                    category_label:
                        text(r,'select.dropdown_topic_sub'),
                    model_value:
                        val(r,'select.dropdown_model'),
                    model_label:
                        text(r,'select.dropdown_model'),
                    machine_value:
                        val(r,'select.dropdown_machine'),
                    machine_label:
                        text(r,'select.dropdown_machine'),
                    start:
                        val(r,'.startCheck input'),
                    end:
                        val(r,'.endCheck input'),
                    description:
                        val(r,'textarea.txt-comment'),
                    process_value:
                        val(
                            r,
                            'select.dropdown_i-tag_process_sub'
                        ),
                    actual_qty:
                        actualQty(r),
                    timeline_text:''
                });
            }

            return out;
        }"""
    )


async def read_result_detail(
    page,
    result_id: str
) -> dict | None:
    result_id = str(
        result_id or ""
    ).strip()

    if not result_id:
        return None

    step = page.locator(
        f'.f1-step[data-result="{result_id}"]:visible'
    ).first

    if await step.count() < 1:
        return None

    try:
        await step.click(
            timeout=5000
        )
    except Exception:
        return None

    deadline = (
        asyncio.get_running_loop().time()
        + 5.0
    )

    while (
        asyncio.get_running_loop().time()
        < deadline
    ):
        forms = page.locator(
            ".task-downtime:visible"
        )

        if await forms.count():
            form = forms.last

            try:
                rid = str(
                    await form.get_attribute(
                        "data-result-id"
                    )
                    or ""
                ).strip()
            except Exception:
                rid = ""

            if (
                not rid
                or rid == result_id
            ):
                detail = await form.evaluate(
                    """root => {
                        const val=(s)=>{
                            const e=root.querySelector(s);
                            return e
                                ? String(
                                    e.value||''
                                ).trim()
                                : '';
                        };

                        const text=(s)=>{
                            const e=root.querySelector(s);
                            if(!e) return '';
                            const o=e.options
                                ? e.options[e.selectedIndex]
                                : null;
                            return String(
                                o ? o.textContent : ''
                            ).trim();
                        };

                        const actualQty=()=>{
                            const inputs=[
                                ...root.querySelectorAll(
                                    'input'
                                )
                            ];

                            for(const el of inputs){
                                const meta=(
                                    String(el.name||'')+' '+
                                    String(el.id||'')+' '+
                                    String(el.className||'')
                                ).toLowerCase();

                                if(meta.includes('actual')){
                                    return String(
                                        el.value||''
                                    ).trim();
                                }

                                const p=el.closest(
                                    '.form-group,.row,[class*="col-"]'
                                );

                                const t=String(
                                    p ? p.innerText : ''
                                ).toLowerCase();

                                if(
                                    t.includes('actual (qty)') ||
                                    t.includes('จำนวนชิ้นงานจริง')
                                ){
                                    return String(
                                        el.value||''
                                    ).trim();
                                }
                            }

                            return '';
                        };

                        return {
                            source:'clicked-form',
                            result_id:String(
                                root.getAttribute(
                                    'data-result-id'
                                )||''
                            ).trim(),
                            topic_value:
                                val('select.dropdown_topic'),
                            topic_label:
                                text('select.dropdown_topic'),
                            category_value:
                                val('select.dropdown_topic_sub'),
                            category_label:
                                text('select.dropdown_topic_sub'),
                            model_value:
                                val('select.dropdown_model'),
                            model_label:
                                text('select.dropdown_model'),
                            machine_value:
                                val('select.dropdown_machine'),
                            machine_label:
                                text('select.dropdown_machine'),
                            start:
                                val('.startCheck input'),
                            end:
                                val('.endCheck input'),
                            description:
                                val('textarea.txt-comment'),
                            process_value:
                                val(
                                    'select.dropdown_i-tag_process_sub'
                                ),
                            actual_qty:
                                actualQty(),
                            timeline_text:''
                        };
                    }"""
                )

                detail["result_id"] = (
                    str(
                        detail.get(
                            "result_id",
                            ""
                        )
                        or result_id
                    ).strip()
                )

                return detail

        await page.wait_for_timeout(
            100
        )

    return None


# Imported lazily to keep this module importable in unit tests without
# requiring asyncio at module import time.
import asyncio


def _complete_enough(
    event: dict
) -> bool:
    """
    A cached record can be reused without clicking if it has the core
    duplicate/update fields.
    """
    return bool(
        str(
            event.get(
                "topic_value",
                ""
            )
            or ""
        ).strip()
        and str(
            event.get(
                "category_value",
                ""
            )
            or ""
        ).strip()
        and str(
            event.get(
                "start",
                ""
            )
            or ""
        ).strip()
    )


async def sync_events_incremental(
    page,
    *,
    cache: QacCache | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[str, dict, list[dict], dict]:
    """
    Persistent incremental QAC synchronization.

    Fast path after first scan:
      timeline IDs -> SQLite IDs -> click only NEW/incomplete Result IDs.
    """
    cache = cache or QacCache()
    identity = await read_document_identity(
        page
    )
    document_key = build_document_key(
        identity["production_date"],
        identity["line"],
        identity["shift"],
        identity["document_no"],
        identity["url"],
    )

    ids = await timeline_result_ids(
        page
    )
    timeline_set = {
        str(x).strip()
        for x in ids
        if str(x).strip()
    }

    # A transiently empty DOM is not proof that QAC deleted all results.
    # Only pay for a second observation when a destructive empty-sync is
    # possible; normal nonempty timelines retain the fast path.
    cached_events = cache.get_events(document_key)
    if not timeline_set and cached_events:
        if progress:
            progress("QAC CACHE empty timeline: verifying before purge")
        await asyncio.sleep(0.35)
        confirmed_ids = await timeline_result_ids(page)
        if confirmed_ids:
            ids = confirmed_ids
            timeline_set = {str(x).strip() for x in ids if str(x).strip()}
            if progress:
                progress("QAC CACHE timeline recovered; preserved old cache")

    # QAC is authoritative only when an actual timeline observation exists.
    # Consecutive empty observations preserve the established deletion rule.
    removed_stale = cache.reconcile_result_ids(
        document_key,
        timeline_set
    )

    if progress and removed_stale:
        progress(
            "QAC CACHE reconcile: "
            f"removed_stale={removed_stale}"
        )

    cached_events = cache.get_events(document_key)
    cached_by_id = {
        str(
            row.get(
                "result_id",
                ""
            )
        ): row
        for row in cached_events
    }

    # DOM detail is cheap and does not click timeline.
    visible = await visible_form_events(
        page
    )
    if visible:
        cache.upsert_events(
            document_key,
            visible
        )

        for row in visible:
            rid = str(
                row.get(
                    "result_id",
                    ""
                )
            )
            if rid:
                cached_by_id[rid] = row

    missing_ids = [
        rid
        for rid in ids
        if (
            rid not in cached_by_id
            or not _complete_enough(
                cached_by_id[rid]
            )
        )
    ]

    if progress:
        progress(
            "QAC CACHE "
            f"timeline={len(ids)} "
            f"cached={len(cached_events)} "
            f"new/detail={len(missing_ids)}"
        )

    details = []

    for index, rid in enumerate(
        missing_ids,
        1
    ):
        if progress:
            progress(
                "QAC CACHE read new "
                f"{index}/{len(missing_ids)} "
                f"Result={rid}"
            )

        detail = await read_result_detail(
            page,
            rid
        )

        if detail:
            details.append(
                detail
            )

    if details:
        cache.upsert_events(
            document_key,
            details
        )

    cache.touch_document(
        document_key,
        production_date=identity["production_date"],
        line=identity["line"],
        shift=identity["shift"],
        document_no=identity["document_no"],
        url=identity["url"],
        timeline_count=len(ids),
    )
    cache.cleanup_keep_today_yesterday()

    events = cache.get_events(
        document_key
    )

    # Return only Result IDs that exist on the current QAC Timeline.
    # Empty Timeline must return [] instead of resurrecting old SQLite rows.
    events = [
        row
        for row in events
        if str(
            row.get(
                "result_id",
                ""
            )
        ) in timeline_set
    ]

    stats = {
        "timeline": len(ids),
        "cached_before": len(
            cached_events
        ),
        "read_details": len(
            details
        ),
        "removed_stale": int(
            removed_stale
        ),
        "returned": len(events),
        "db_path": str(
            cache.path
        ),
    }

    return (
        document_key,
        identity,
        events,
        stats,
    )


async def cache_saved_result(
    page,
    result_id: str,
    *,
    cache: QacCache | None = None,
) -> dict | None:
    """
    Update SQLite immediately after this program saves/updates a QAC Result.
    Only the one Result is read.
    """
    cache = cache or QacCache()
    identity = await read_document_identity(
        page
    )
    document_key = build_document_key(
        identity["production_date"],
        identity["line"],
        identity["shift"],
        identity["document_no"],
        identity["url"],
    )

    detail = await read_result_detail(
        page,
        result_id
    )

    if detail:
        cache.upsert_events(
            document_key,
            [detail]
        )

    ids = await timeline_result_ids(
        page
    )

    cache.touch_document(
        document_key,
        production_date=identity["production_date"],
        line=identity["line"],
        shift=identity["shift"],
        document_no=identity["document_no"],
        url=identity["url"],
        timeline_count=len(ids),
    )

    return detail



async def cache_event_payload(
    page,
    result_id: str,
    event: dict,
    *,
    cache: QacCache | None = None,
) -> dict:
    """
    Fast post-save cache write.

    Uses the values already submitted by this program and therefore does not
    click/reopen the saved QAC Result.
    """
    cache = cache or QacCache()
    identity = await read_document_identity(
        page
    )
    document_key = build_document_key(
        identity["production_date"],
        identity["line"],
        identity["shift"],
        identity["document_no"],
        identity["url"],
    )

    payload = dict(
        event or {}
    )
    payload["result_id"] = str(
        result_id or ""
    ).strip()
    payload.setdefault(
        "source",
        "program-save"
    )

    cache.upsert_events(
        document_key,
        [payload]
    )

    ids = await timeline_result_ids(
        page
    )

    cache.touch_document(
        document_key,
        production_date=identity["production_date"],
        line=identity["line"],
        shift=identity["shift"],
        document_no=identity["document_no"],
        url=identity["url"],
        timeline_count=len(ids),
    )

    return payload
