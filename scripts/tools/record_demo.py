"""Drive the real app in a browser and record it, for the README demo.

    uv run python scripts/tools/record_demo.py                 # light
    uv run python scripts/tools/record_demo.py --theme dark
    uv run python scripts/tools/record_demo.py --headed        # watch it happen

What it produces lands in `assets/demo/<theme>/` — a WebM of the whole session, plus a
numbered PNG at each step so a still can be picked without scrubbing the video.

WHY A RECORDING AND NOT A DRAWING. The README used to show `demo-*.svg`, drawn by a script
from values typed into it: sharp, diffable, and a screen that had never existed. This one
signs in, asks the questions, waits for real agents to answer them, opens a tool call to
show the SQL underneath, and scrolls the real dashboard. It is slower, it needs the stack
up, and it can be wrong in the way the product is wrong — which is the point.

WHAT THE README SHOWS. A take lands in `assets/demo/<theme>/`, which is ignored. Promoting
one is a decision, not an outcome of running this: copy the WebM to `assets/demo.webm` and
a still to `assets/demo-poster.png`. A recording nobody looked at is not a demo.

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

#: Two, and both of them reach for the work data. The weekly-summary question used to open
#: the set and it is gone: it reads as a greeting, it costs a full multi-agent run, and a
#: viewer learns from it exactly what the next two show properly.
QUESTIONS = [
    "Who logged the most hours this month, and on what?",
    "What is late right now, and who is it with?",
]

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
    true the instant Enter is pressed. That is what sent the next question on top of a
    question still being answered.
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
    await page.get_by_role("button", name="Running").wait_for(timeout=30_000)
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
            await reveal_tool(page, shot, tag)
        except PlaywrightTimeout as exc:
            print(f"  tool reveal skipped: {exc}")


async def watch_live(page: Page, shot: Shot, tag: str) -> None:
    """Follow the run while it is still running, instead of waiting for it in silence.

    The other question is watched from the top, which shows the product as a box that goes
    quiet and then returns a paragraph. This one follows the page down as the stream writes
    into it: each tool call arrives as its own row, with a spinner on the one that is out,
    and that is the thing a finished answer can no longer show.

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


async def reveal_tool(page: Page, shot: Shot, tag: str) -> None:
    """Open the last tool call, so the video shows the SQL the answer rests on.

    This is the claim the product makes that a screenshot of prose cannot: the figures are
    not the model's recollection, and here is the query that produced them. Skipped without
    complaint when a run answered from memory and called nothing.
    """
    # `:visible` matters: a tool call can nest, and a nested row lives inside a parent
    # `<details>` that is still shut. Taking the last row without that filter picks a row
    # that is in the DOM and not on the screen, and the click waits out its timeout.
    rows = page.locator("details.tool > summary:visible")
    if await rows.count() == 0:
        return
    row = rows.last
    await click(page, row, after=1.0)
    # The panel expands into space below it; scroll only if it opened off screen.
    await row.scroll_into_view_if_needed()
    await settle(page, 1.4)
    await shot(f"{tag}-tool-open")
    await glide(page, 260, steps=10)
    await settle(page, 1.6)
    await shot(f"{tag}-tool-read")
    await click(page, row, after=1.0)


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
            await sign_in(page, shot)
            # The two questions are shown differently on purpose. The first is watched the
            # way a user waits — from the top — and its tool call is opened afterwards, at
            # rest, where the SQL can be read. The second is followed down while it runs,
            # so the video also carries what the stream looks like in flight.
            await ask(page, QUESTIONS[0], shot, "q1", open_tool=True)
            await ask(page, QUESTIONS[1], shot, "q2", watch=True)
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
