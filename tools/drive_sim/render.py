from __future__ import annotations

from html import escape
from math import cos, sin
from pathlib import Path

from .scenarios import ScenarioResult


def _scale_points(result: ScenarioResult, width: int = 280, height: int = 180) -> list[tuple[float, float]]:
    poses = [sample.pose for sample in result.trajectory.samples]
    xs = [pose.x_m for pose in poses]
    ys = [pose.y_m for pose in poses]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(0.05, max_x - min_x)
    span_y = max(0.05, max_y - min_y)
    scale = min((width - 40) / span_x, (height - 40) / span_y)
    cx = (min_x + max_x) / 2.0
    cy = (min_y + max_y) / 2.0
    return [
        (width / 2 + (pose.x_m - cx) * scale, height / 2 - (pose.y_m - cy) * scale)
        for pose in poses
    ]


def _scenario_svg(result: ScenarioResult, width: int = 280, height: int = 180) -> str:
    points = _scale_points(result, width, height)
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    start = points[0]
    end = points[-1]
    end_pose = result.trajectory.end
    arrow_len = 18
    hx = end[0] + cos(end_pose.theta_rad) * arrow_len
    hy = end[1] - sin(end_pose.theta_rad) * arrow_len
    return f"""
    <svg class=\"plot\" viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"{escape(result.name)} trajectory\">
      <defs><marker id=\"arrow-{escape(result.name)}\" viewBox=\"0 0 10 10\" refX=\"8\" refY=\"5\" markerWidth=\"5\" markerHeight=\"5\" orient=\"auto\"><path d=\"M2 1 L8 5 L2 9\" fill=\"none\" stroke=\"#D97757\" stroke-width=\"1.5\" stroke-linecap=\"round\"/></marker></defs>
      <rect x=\"1\" y=\"1\" width=\"{width-2}\" height=\"{height-2}\" rx=\"12\" />
      <polyline points=\"{path}\" />
      <circle class=\"start\" cx=\"{start[0]:.1f}\" cy=\"{start[1]:.1f}\" r=\"4\" />
      <circle class=\"end\" cx=\"{end[0]:.1f}\" cy=\"{end[1]:.1f}\" r=\"4\" />
      <line class=\"heading\" x1=\"{end[0]:.1f}\" y1=\"{end[1]:.1f}\" x2=\"{hx:.1f}\" y2=\"{hy:.1f}\" marker-end=\"url(#arrow-{escape(result.name)})\" />
    </svg>
    """


def render_report(results: list[ScenarioResult], output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    cards = []
    for result in results:
        metrics = result.trajectory.metrics()
        badge = "pass" if result.passed else "fail"
        checks = "".join(
            f"<li class='{ 'ok' if check.passed else 'bad' }'><span>{escape(check.name)}</span><code>{escape(check.detail)}</code></li>"
            for check in result.assertion_results
        )
        cards.append(f"""
        <section class=\"card\">
          <div class=\"card-head\"><h2>{escape(result.name)}</h2><span class=\"badge {badge}\">{badge.upper()}</span></div>
          <div class=\"kind\">{escape(result.kind)}</div>
          <p class=\"desc\">{escape(result.description)}</p>
          {_scenario_svg(result)}
          <div class=\"metrics\">
            <div><strong>{metrics['forward_displacement_m']:.2f}m</strong><span>forward</span></div>
            <div><strong>{metrics['heading_delta_deg']:.1f}°</strong><span>heading</span></div>
            <div><strong>{metrics['final_speed_mps']:.2f}</strong><span>final m/s</span></div>
          </div>
          <ul class=\"checks\">{checks}</ul>
        </section>
        """)
    html = f"""<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\" />
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
<title>Virtual Drive Simulator Report</title>
<style>
:root{{--ivory:#FAF9F5;--white:#fff;--slate:#141413;--clay:#D97757;--olive:#788C5D;--rust:#B04A3F;--oat:#E3DACC;--gray-150:#F0EEE6;--gray-300:#D1CFC5;--gray-500:#87867F;--gray-700:#3D3D3A;--mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;--serif:ui-serif,Georgia,serif;--sans:system-ui,-apple-system,"Segoe UI",sans-serif}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--ivory);color:var(--gray-700);font-family:var(--sans);padding:42px 24px 80px}}.page{{max-width:1120px;margin:0 auto}}.eyebrow{{font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--gray-500)}}h1,h2{{font-family:var(--serif);font-weight:500;color:var(--slate);letter-spacing:-.01em}}h1{{font-size:42px;margin:.2em 0 .15em}}.summary{{font-size:18px;margin-bottom:28px}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:18px}}.card{{background:var(--white);border:1.5px solid var(--gray-300);border-radius:14px;padding:16px}}.card-head{{display:flex;justify-content:space-between;gap:12px;align-items:start}}h2{{font-size:21px;margin:0}}.kind{{font-family:var(--mono);font-size:11px;text-transform:uppercase;color:var(--gray-500);margin:3px 0 8px}}.desc{{font-size:12.5px;color:var(--gray-500);min-height:38px;margin:0 0 10px}}.badge{{font-family:var(--mono);font-size:11px;border-radius:999px;padding:4px 9px}}.badge.pass{{background:rgba(120,140,93,.17);color:var(--olive)}}.badge.fail{{background:rgba(176,74,63,.15);color:var(--rust)}}.plot{{width:100%;height:auto;margin:8px 0 10px}}.plot rect{{fill:var(--gray-150);stroke:var(--gray-300)}}.plot polyline{{fill:none;stroke:var(--clay);stroke-width:3;stroke-linecap:round;stroke-linejoin:round}}.plot .start{{fill:var(--olive)}}.plot .end{{fill:var(--clay)}}.plot .heading{{stroke:var(--clay);stroke-width:2}}.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}}.metrics div{{background:var(--gray-150);border-radius:9px;padding:8px}}.metrics strong{{display:block;color:var(--slate);font-family:var(--serif);font-size:21px;font-weight:500}}.metrics span{{font-family:var(--mono);font-size:10px;text-transform:uppercase;color:var(--gray-500)}}.checks{{list-style:none;padding:0;margin:10px 0 0}}.checks li{{display:flex;justify-content:space-between;gap:8px;border-top:1px solid var(--gray-150);padding:8px 0;font-size:13px}}.checks code{{font-family:var(--mono);font-size:11px;color:var(--gray-500)}}.checks .ok span{{color:var(--olive)}}.checks .bad span{{color:var(--rust)}}
</style>
</head>
<body><div class=\"page\"><div class=\"eyebrow\">Combat Robot Controller v2</div><h1>Virtual Drive Simulator Report</h1><p class=\"summary\">{passed}/{total} scenarios passed. These are kinematic drive-logic checks, not full physics simulations.</p><div class=\"grid\">{''.join(cards)}</div></div></body></html>"""
    output.write_text(html, encoding="utf-8")
    return output
