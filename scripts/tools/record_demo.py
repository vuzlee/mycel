"""Drive the real app in a browser and record it, for the README demo.

    uv run python scripts/tools/record_demo.py                 # light
    uv run python scripts/tools/record_demo.py --theme dark
    uv run python scripts/tools/record_demo.py --headed        # watch it happen

What it produces lands in `assets/demo/<theme>/` — a WebM of the whole session, plus a
numbered PNG at each step so a still can be picked without scrubbing the video.

WHY A RECORDING AND NOT A DRAWING. The README used to show `demo-*.svg`, drawn by a script
from values typed into it: sharp, diffable, and a screen that had never existed. This one
signs in, asks a question, waits for real agents to answer it, rereads the run step by
step with every tool call opened, and scrolls the real dashboard. It is slower, it
needs the stack up, and it can be wrong in the way the product is wrong — which is the point.

WHAT THE README SHOWS. A take lands in `assets/demo/<theme>/`, which is ignored, and nothing
here publishes it. GitHub gives a player only to a `user-attachments` URL, and one of those
exists only for a file dropped into a comment box — so promoting a take is done by hand:
watch it, drop it into a new issue, and put the URL it returns in the README. A recording
nobody looked at is not a demo, and the upload is the step that guarantees someone did.

IT IS PACED FOR A WATCHER, NOT FOR A TEST. A test clicks the moment an element exists; a
person moves the pointer there, pauses, and reads what happened. So every click travels,
every field is typed a character at a time, and every scroll is a short glide with a beat
after it. The result is about two minutes of video where a test would take twenty seconds,
and all of the difference is deliberate.

WHAT IT NEEDS. `scripts/stack.sh up`, a built `web/dist` — the API serves the bundle from
disk, so a CSS change not yet built will not appear. The account it uses is DEMO_EMAIL
with DEMO_PASSWORD, and it has to exist already — registering it on camera was tried and
cut, because the one screen a demo is for is the product, not the sign-up form.
Nothing is written to Jira: every question in here is a read.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
from pathlib import Path

from playwright.async_api import Locator, Page, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeout

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "assets" / "demo"

#: The account the video is recorded as. An address nobody reads mail at, because what
#: ends up on screen is the address, and a real one would be published with the README.
EMAIL = os.environ.get("DEMO_EMAIL", "demo@gmail.com")
PASSWORD = os.environ.get("DEMO_PASSWORD", "mycel-demo-2026")

#: What the demo account is allowed to read. Registration grants nothing — membership is
#: closed by default and deliberately so — and an account with no grant can sign in and
#: then see an empty answer to every question.
PROJECT = os.environ.get("DEMO_PROJECT", "MYC")

BASE = os.environ.get("DEMO_BASE_URL", "http://localhost:8000")
APP = f"{BASE}/app"

#: 720p. Small enough to commit a still from, large enough that the SQL inside an opened
#: tool call is readable rather than implied.
VIEWPORT = {"width": 1280, "height": 800}

#: How long the title card is held. GitHub strips a `<video>` tag out of a README, so
#: `poster=` never reaches the page and the thumbnail is whatever the FIRST FRAME is — the
#: only place a thumbnail can be authored is inside the recording itself. Long enough to
#: read the line under the name, and it is also what the still is cut from.
CARD_MS = 2600

#: The two palettes the card is drawn in, taken from the app's own tokens rather than
#: chosen here: a thumbnail in colours the product does not use is a thumbnail for a
#: different product.
PALETTE = {
    "light": {
        "bg": "#ffffff",
        "mark": "#6d3fd1",
        "glyph": "#ffffff",
        "ink": "#17141f",
        "dim": "#6b6478",
        "edge": "#e8e4f0",
    },
    "dark": {
        "bg": "#0b0910",
        "mark": "#b79cff",
        "glyph": "#14101d",
        "ink": "#f0edf7",
        "dim": "#8f87a3",
        "edge": "#241f30",
    },
}

#: One question, and it reaches for the work data. Two others were tried and cut: a
#: weekly-summary opener that read as a greeting, and an overdue question whose honest
#: answer here is "none", because this project sets a due date on almost nothing — an
#: answer of zero teaches a viewer that the product found nothing rather than that the
#: field is empty. This one names a person, a figure and the rows behind both.
QUESTION = "Who logged the most hours this month, and on what?"

#: A run is a queue hop plus a model call plus tools. Two minutes is not generous.
ANSWER_MS = 120_000

#: The beat between finishing one thing and starting the next. Long enough to read a short
#: line, short enough that the video does not feel like it is waiting for something.
BEAT = 900

#: Milliseconds per keystroke. Fast typing reads as a machine, slow reads as hesitation.
KEY = 42


async def settle(page: Page, beats: float = 1.0) -> None:
    """A pause measured in beats rather than milliseconds, so the whole video's pace is one
    number to change."""
    await page.wait_for_timeout(int(BEAT * beats))


async def move_to(page: Page, target: Locator) -> None:
    """Send the pointer to something in a few steps instead of teleporting.

    A cursor that jumps makes every click look like it happened to a different page. The
    steps are what the video sees; nothing about the click depends on them.
    """
    await target.scroll_into_view_if_needed()
    box = await target.bounding_box()
    if box is None:
        return
    await page.mouse.move(
        box["x"] + box["width"] / 2,
        box["y"] + box["height"] / 2,
        steps=22,
    )
    await page.wait_for_timeout(180)


async def click(page: Page, target: Locator, after: float = 1.0) -> None:
    """Travel to it, press it, and hold still long enough to see what it did."""
    await move_to(page, target)
    await target.click()
    await settle(page, after)


async def glide(page: Page, distance: int, steps: int = 14) -> None:
    """Scroll the way a wheel does: many small notches, not one jump.

    `mouse.wheel` in one call moves the whole distance in a single frame, which in a
    recording is a cut rather than a scroll.
    """
    step = distance // steps
    for _ in range(steps):
        await page.mouse.wheel(0, step)
        await page.wait_for_timeout(28)


class Shot:
    """Numbered stills, in the order they were taken."""

    def __init__(self, page: Page, out: Path) -> None:
        self._page = page
        self._out = out
        self._n = 0

    async def __call__(self, name: str) -> None:
        self._n += 1
        await self._page.screenshot(path=self._out / f"{self._n:02d}-{name}.png")


async def title_card(page: Page, shot: Shot, theme: str) -> None:
    """Open on the app's mark and its name, so the still the video is represented by says
    what it is.

    Not a poster file. GitHub removes the `<video>` element from a README outright, which
    takes `poster=` with it, and the player it puts in place of a bare attachment URL uses
    the first frame — so the thumbnail is a recording decision, not a markup one. Drawn
    here rather than committed as a PNG for the same reason a take is not committed: it is
    derived from the recording and would go stale the moment either changes.

    `set_content` rather than a page of the app. The card is not a screen the product has,
    and dressing up a real screen to look like one would be the staging this whole tool
    exists to avoid.
    """
    skin = PALETTE[theme]
    await page.set_content(
        f"""<!doctype html><meta charset=utf-8>
<link rel=preconnect href=https://fonts.gstatic.com crossorigin>
<link rel=stylesheet href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500\
&family=Instrument+Serif&display=swap">
<style>
  html,body {{ height:100%; margin:0 }}
  body {{ background:{skin["bg"]}; color:{skin["ink"]};
         display:flex; align-items:center; justify-content:center;
         font-family:Geist,ui-sans-serif,system-ui,sans-serif }}
  .card {{ display:flex; align-items:center; gap:28px }}
  .rule {{ width:1px; height:104px; background:{skin["edge"]} }}
  h1 {{ font-family:"Instrument Serif",Georgia,serif; font-size:76px;
        font-weight:400; margin:0 0 6px; letter-spacing:-.01em; line-height:1 }}
  p {{ margin:0; font-size:19px; color:{skin["dim"]} }}
  .foot {{ margin-top:14px; font-size:14px; color:{skin["dim"]}; letter-spacing:.02em }}
</style>
<div class=card>
  <svg width=112 height=112 viewBox="0 0 32 32" aria-label=Mycel>
    <rect width=32 height=32 rx=9 fill="{skin["mark"]}"/>
    <g transform="translate(4 4) scale(1.5)" fill=none stroke="{skin["glyph"]}"
       stroke-width=1.3 stroke-linecap=round stroke-linejoin=round>
      <path d="M8 8.6V13"/>
      <path d="M8 8.6 4.1 5.4M4.1 5.4V2.9M4.1 5.4H1.9"/>
      <path d="M8 8.6 12.1 5.9M12.1 5.9l1.9-1.6M12.1 5.9l.5 2.3"/>
      <circle cx=8 cy=8.6 r=1.25 fill="{skin["glyph"]}" stroke=none/>
    </g>
  </svg>
  <div class=rule></div>
  <div>
    <h1>Mycel</h1>
    <p>Ask your issue tracker a question in plain language.</p>
    <div class=foot>A real session. Nothing staged.</div>
  </div>
</div>"""
    )
    # The webfonts land a frame or two late, and a card screenshotted before they do is a
    # card in the fallback serif — which is the one frame everybody sees.
    await page.evaluate("() => document.fonts.ready")
    await page.wait_for_timeout(CARD_MS)
    await shot("card")


async def sign_in(page: Page, shot: Shot) -> None:
    await page.goto(f"{APP}/login")
    await settle(page, 1.4)
    await shot("login")

    await click(page, page.get_by_label("Email"), after=0.2)
    await page.keyboard.type(EMAIL, delay=KEY)
    await settle(page, 0.4)

    await click(page, page.get_by_label("Password"), after=0.2)
    await page.keyboard.type(PASSWORD, delay=KEY)
    await settle(page, 0.7)

    await click(page, page.get_by_role("button", name="Sign in"), after=0)
    # The composer is the proof: it only renders once the session is real.
    await page.get_by_label("Your question").wait_for(timeout=30_000)
    await settle(page, 1.6)
    await shot("signed-in")


async def grant_project() -> None:
    """Give the demo account the project, the way a shell would.

    Not through the browser: granting is an administrator's screen and it is not part of
    the story the video tells. Granting twice is not an error, so this runs every time.
    """
    from mycel.infra.postgres.repositories.app import AppRepository
    from mycel.infra.postgres.session import session_scope

    async with session_scope() as session:
        repo = AppRepository(session)
        user = await repo.user_by_email(EMAIL)
        if user is None:
            raise SystemExit(f"no account for {EMAIL} — register it once before recording")
        await repo.grant_project(user.id, PROJECT)


async def ask(
    page: Page, question: str, shot: Shot, tag: str, open_tool: bool = False, watch: bool = False
) -> None:
    """Ask one question and wait for THIS run to be over.

    Waits on the send button, not on the answer. `Answer` renders nothing while the stream
    is the thing showing the text — which is every live run — so "an answer element
    appeared" is a condition that never comes true here. The button is the honest signal:
    it carries "Running" for exactly as long as the run is open, and returns to "Ask"
    whether the run ended well or badly.

    Both edges are waited on, in order, and the first one is the whole point. The label is
    "Ask" before the run starts too — the job has to be created and its stream opened
    before anything is `running` — so waiting only for "Ask" is a condition that is already
    true the instant Enter is pressed, and everything after it would run on a page still
    being written into.
    """
    box = page.get_by_label("Your question")
    await click(page, box, after=0.3)
    # Typed rather than filled. The demo is about watching someone use it, and a field that
    # fills instantly reads as a screenshot with text pasted into it.
    await page.keyboard.type(question, delay=KEY)
    await settle(page, 0.8)
    await shot(f"{tag}-typed")

    await page.keyboard.press("Enter")
    await page.locator(".turn.user").last.wait_for(timeout=15_000)
    # The run has actually started once the button says so. A few seconds is generous: it
    # is one POST and the stream opening, not the model.
    #
    # Tolerated, because "Running" is a label this can miss rather than a state it needs:
    # a run that fails at the first provider call — a rate limit is the usual one — is
    # open for less than a poll, and the far edge below is then already true. Losing the
    # recording at that point throws away every minute before it, which is the worse end.
    try:
        await page.get_by_role("button", name="Running").wait_for(timeout=30_000)
    except PlaywrightTimeout:
        print(f"  {tag}: never saw Running — the run ended as fast as it started")
    await settle(page, 1.8)
    await shot(f"{tag}-running")

    if watch:
        await watch_live(page, shot, tag)

    # And now the far edge: back to "Ask". Long, because a multi-agent run is minutes and
    # because a provider under a rate limit retries before it gives up.
    await page.get_by_role("button", name="Ask").wait_for(timeout=ANSWER_MS)
    await settle(page, 2.0)
    await shot(f"{tag}-answered")

    if open_tool:
        # Best-effort. The reveal is a flourish, and losing the whole recording minutes in
        # because one panel would not open is a bad trade — the run costs real money.
        try:
            await review_steps(page, shot, tag)
        except PlaywrightTimeout as exc:
            print(f"  step review skipped: {exc}")


async def watch_live(page: Page, shot: Shot, tag: str) -> None:
    """Follow the run while it is still running, instead of waiting for it in silence.

    Waited out from the top, the product is a box that goes quiet and then returns a
    paragraph. Followed down as the stream writes into it, each tool call arrives as its
    own row with a spinner on the one that is out — and that is the thing a finished
    answer can no longer show.

    Stops as soon as the run does, so a fast run is not padded with scrolling after it.
    """
    for index in range(1, 5):
        # A short glide each pass. The stream appends below the fold, so following it is
        # the same motion a reader makes, not a jump to the bottom.
        await glide(page, 320, steps=10)
        await settle(page, 1.5)
        await shot(f"{tag}-live-{index}")
        if await page.get_by_role("button", name="Ask").count() > 0:
            return


async def review_steps(page: Page, shot: Shot, tag: str) -> None:
    """Walk back up the finished run and read what it actually did.

    The answer is the least interesting part of a multi-agent run, because it is the part
    every one of these products has. What is above it is the claim: an orchestrator that
    thought, delegated to named agents, and called tools whose arguments and results are
    on the page. A viewer who only sees the paragraph has to take that on faith.

    So this goes back to the question and comes down through the steps in order, opening
    every tool call on the way. That is the reverse of how the run was watched live — up
    to the top, then down slowly — and it is the motion of rereading rather than waiting.

    Best-effort throughout. A run that answered from memory called nothing, and there is
    then simply less to walk through; that is not a failure worth losing a recording to.
    """
    # Back to the question first. The steps are between it and the answer, and starting
    # from the bottom would show them in the order they were not produced in.
    await glide(page, -2200, steps=22)
    await settle(page, 1.4)
    await shot(f"{tag}-steps-top")

    # `:visible` matters: a tool call can nest, and a nested row lives inside a parent
    # `<details>` that is still shut. A row that is in the DOM and not on the screen
    # cannot be clicked, and the click waits out its whole timeout instead of failing.
    #
    # Re-read on each pass rather than taken once: opening a parent row puts its children
    # on screen, and those are rows this loop should walk into as well.
    seen = 0
    for index in range(1, 7):
        rows = page.locator("details.tool > summary:visible")
        count = await rows.count()
        if seen >= count:
            # Nothing new came into view, so the glide below is what moves this along.
            await glide(page, 300, steps=12)
            await settle(page, 1.2)
            if await at_bottom(page):
                break
            continue
        row = rows.nth(seen)
        seen += 1
        await click(page, row, after=1.2)
        # The panel expands downward. Reading it is a short glide, not a jump: the
        # arguments are at the top of it and the result is below them.
        await glide(page, 240, steps=10)
        await settle(page, 1.6)
        await shot(f"{tag}-step-{index}")

    await settle(page, 1.2)
    await shot(f"{tag}-steps-read")


async def at_bottom(page: Page) -> bool:
    """Whether the scroller has nothing left below it.

    The thread scrolls inside `.scroll`, not in the document: the app is a full-height
    flex column and the window itself never scrolls. Asking the document here would
    answer "at the bottom" on the first pass and cut the review short.

    A few pixels of slack, because a fractional scroll height never lands exactly.
    """
    return bool(
        await page.evaluate(
            "() => { const el = document.querySelector('.scroll');"
            "  return el === null || el.scrollTop + el.clientHeight >= el.scrollHeight - 4; }"
        )
    )


async def show_dashboard(page: Page, shot: Shot) -> None:
    await click(page, page.get_by_role("button", name="Dashboard"), after=0)
    await page.locator(".page.board").wait_for(timeout=30_000)
    await settle(page, 2.2)
    await shot("dashboard-top")

    # One window button, because the dashboard's own claim is that the numbers move with
    # the question you are asking of them.
    window = page.get_by_role("button", name="30d")
    if await window.count() > 0:
        await click(page, window.first, after=1.8)
        await shot("dashboard-30d")

    # Scrolled in stages rather than jumped to the bottom: the point is that the page keeps
    # going, and a cut from the top to the end does not show that.
    for step in range(1, 5):
        await glide(page, 560)
        await settle(page, 1.3)
        await shot(f"dashboard-{step}")

    await glide(page, -2400, steps=24)
    await settle(page, 1.4)
    await shot("dashboard-back")


async def record(theme: str, headed: bool) -> int:
    out = OUT / theme
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    async with async_playwright() as play:
        browser = await play.chromium.launch(headless=not headed)
        context = await browser.new_context(
            viewport=VIEWPORT,
            color_scheme=theme,  # type: ignore[arg-type]
            record_video_dir=str(out),
            record_video_size=VIEWPORT,
            # A recording at 1x on a HiDPI screen is soft. Two is the sharpest the video
            # writer takes without the file becoming the reason nobody plays it.
            device_scale_factor=2,
            # The app's own transitions are part of what is being shown. Asking for reduced
            # motion here would record a version of the product nobody uses.
            reduced_motion="no-preference",
        )
        page = await context.new_page()
        shot = Shot(page, out)

        try:
            # Before the first question: an account with no grant signs in fine and then
            # answers every question with nothing.
            await grant_project()
            # First, and before anything the app draws: this frame is the thumbnail.
            await title_card(page, shot, theme)
            await sign_in(page, shot)
            # One question, carrying both halves of what a run looks like: followed down
            # while it streams, so the video has the tool calls arriving one at a time,
            # and then reread from the top with every call opened, which is where the
            # product's actual claim sits. A second question was cut — it asked different
            # data and the same product, so it bought a viewer nothing and cost a minute,
            # a full multi-agent run, and a wait for the free tier's per-minute window.
            await ask(page, QUESTION, shot, "q1", open_tool=True, watch=True)
            await show_dashboard(page, shot)
        finally:
            # Closing the context is what flushes the video. It has to happen even on a
            # failure, or a run that got most of the way through leaves nothing at all.
            await context.close()
            await browser.close()

    video = next((p for p in out.glob("*.webm")), None)
    if video is not None:
        video.rename(out / "demo.webm")

    print(f"\n{out.relative_to(ROOT)}")
    for path in sorted(out.iterdir()):
        print(f"  {path.name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    parser.add_argument("--headed", action="store_true", help="show the browser")
    args = parser.parse_args()
    return asyncio.run(record(args.theme, args.headed))


if __name__ == "__main__":
    raise SystemExit(main())
