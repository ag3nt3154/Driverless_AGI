---
title: 'Firefox WebDriver computed ARIA role is empty for date and password inputs'
description: 'Selenium aria_role on Firefox 157 returns "" for some inputs, so dagi builds its own DOM outline (rpa/drivers/outline.js) and uses computed role only as a cross-check.'
tags: [rpa, firefox, geckodriver, selenium, aria_role, computed role, outline.js, FirefoxDriver]
updated: 2026-10-12
---
Found in the RPA S0 browser spike (2026-10-10, Firefox 157.0.1 + geckodriver 0.37.1).

- `WebElement.aria_role` (WebDriver "Get Computed Role") returns an empty string for
  `<input type="date">` and `<input type="password">` in Firefox. Locators built on it
  would be missing exactly the fields a workflow needs most.
- dagi therefore injects its own outline script, `rpa/drivers/outline.js`: a DOM walk that
  derives role and accessible name itself, records bboxes, marks password fields secure,
  and tags nodes with `data-dagi-i` for re-identification (`WrongElement` check in `act`).
- Limits of the script (v1): no iframe or shadow-DOM traversal; `aria-hidden` is not checked.
