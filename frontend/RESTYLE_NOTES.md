# Restyle notes (frontend only; backend, routes and tests are unchanged)
1. **Theme:** all colours, radii, fonts and timings are CSS variables at the top of `styles.css` (`--accent`, `--surface`, `--r-lg`, `--ease`, `--t`). Change them there and the whole app follows.
2. **Course colours:** `app.js` only sets a hue per course; lightness comes from `--cc-bg / --cc-bd / --cc-fg`, so seats stay readable on the dark theme.
3. **Animations:** all JS animation lives in `motion.js` (Web Animations API: tab pill, stagger, seat pop, count-up, toasts, skeleton); hover/press/focus are CSS in `styles.css`.
4. **Rules kept:** only transform/opacity are animated (the tab label colour fade is the one exception), 150–350 ms, one easing; `prefers-reduced-motion` turns everything off.
5. **Run:** `uvicorn app:app --reload` as before; Inter loads from Google Fonts (falls back to system fonts offline).
6. **Step 7 (theme):** dark is the default. `:root[data-theme="light"]` in `styles.css` overrides the same tokens; hatch, shimmer and top-bar colours are now variables too. `--accent-text` is the text-safe amber (WCAG AA on the light cards). The toggle code is at the top of `app.js`; the no-flash script is in the `<head>` of `index.html`.
7. **PDF check screen:** the line under "This list is for" says whether loading replaces an existing list or adds a new one.

8. **Cosmetic pass:** timetable rows read as text; the pencil opens one row for editing and the tick closes it. The table is grouped by date by default ("Group by" picks another field; it only changes the view). Room grids sit centred under the "front of room" line. Each chosen file has its own × on the Data tab (student files add up, rooms/schedule swap). The Rooms help card, the provisional banner, the room Notes box and the timetable intro text are gone (a room's note is still kept and saved).
