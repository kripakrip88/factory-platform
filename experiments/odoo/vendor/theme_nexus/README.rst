.. image:: https://img.shields.io/badge/license-LGPL--3-green.svg
    :target: https://www.gnu.org/licenses/lgpl-3.0-standalone.html
    :alt: License: LGPL-3

NEXUS Backend Theme
====================
A modern enterprise backend theme for **Odoo 18 Community**: a persistent
dark application sidebar with an orange accent, bright rounded content
cards, and a built-in Light / Dark content toggle.

Features
--------
- Persistent left application sidebar — pinned on desktop (>= 1200px),
  slides in as a drawer with a backdrop on smaller screens
- Light / Dark content mode toggle (persisted in the browser via
  ``localStorage``)
- Restyled buttons, form sheet, statusbar, notebook tabs
- Restyled list, kanban, and calendar views
- Restyled modals / dialogs, notifications, scrollbars, focus rings
- No external font / CDN dependency — safe on offline / air-gapped
  installs
- Pure front-end module: no server-side models, no data migrations

Installation
============
1. Copy the ``theme_nexus`` folder into your Odoo ``addons`` path
   (or a custom addons directory already added to ``odoo.conf``).
2. Restart the Odoo server.
3. Apps → toggle *Developer Mode* if the theme doesn't show up →
   **Update Apps List**.
4. Search for **NEXUS Backend Theme** and click **Install**.
5. Hard-refresh the browser (Ctrl/Cmd + Shift + R) to clear the old
   assets bundle cache.

Usage
-----
- Click the grid icon at the top-left of the navbar to collapse /
  expand the application sidebar.
- Click **Dark Mode** at the bottom of the sidebar to switch the
  content area between light and dark.

Compatibility notes
--------------------
This theme patches the core ``NavBar`` OWL component and inherits its
template via ``t-inherit``. It has been written against the Odoo 18.0
web client structure. If you are on a fork, a heavily customized
``web`` module, or a different Odoo version, test in a staging
database before deploying to production — a differing DOM structure
in ``NavBar`` could require adjusting the ``xpath`` selectors in
``static/src/xml/navbar.xml``.

License
-------
GNU Lesser General Public License, Version 3 (LGPL v3).

Credits
-------
Designed & developed by **Hồng Ngọc Phú**
Industrial Management Researcher — Can Tho University
