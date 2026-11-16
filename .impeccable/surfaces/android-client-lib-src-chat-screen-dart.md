---
version: 1
slug: "android-client-lib-src-chat-screen-dart"
primary_target: "Android_Client/lib/src/chat_screen.dart"
related_targets: ["ChelsyAI_0.9_Windows/client_gui.py","ChelsyAI_0.9_Windows/app.py"]
---

# Surface brief: Chelsy chat (Android, Windows Client, Desktop)

Scope: the main chat surface and its sidebar/drawer, login, research/knowledge views on all three apps. Mode: Operate.
Audience and job: public Russian-speaking users ask, read answers with sources, continue chats across devices.
Constraints: binding brand palette and logo (PRODUCT.md); standard platform navigation and controls; Tkinter-only on Windows, Material 3 on Android, Gradio on Desktop.
Fixes owed: readable code blocks on Android, legible text on primary buttons, italics in Windows Client, Russian research statuses, no clipped toolbar buttons.

## Direction contract

THESIS: A calm polar-night chat where the only light is Chelsy working: the aurora appears when she thinks, searches or syncs, and rests as a thin horizon otherwise. Refuses the category default of glowing neon cards and gradient blobs everywhere.

OWN-WORLD: Polar-night ground #0B0C20 with two tonal lifts (#11132B panels, #161937 fields); snow text #ECEBFA, frost-muted #A3A6C8. Aurora = brand gradient violet #6D4AFF → lavender #A78BFA → turquoise #21D9DA, used only for the horizon band, the primary action and the active-row edge. Soft radii (12–20), no borders on Chelsy's answers, user turns in a quiet raised bubble, dates in turquoise tabular figures.

STORY: The user sees the conversation first, knows Chelsy's state from the horizon without reading a label, sees which sources and dates an answer used, and acts with standard controls.

FIRST VIEWPORT: Platform top bar (title, state dot, favourite, menu) → wide reading column (user bubble right, Chelsy text left with logo avatar, sources block with turquoise dates) → composer pinned bottom with the aurora horizon along its top edge, send/stop in one spot, model and internet toggle beneath. Drawer/sidebar: new chat (primary violet), search, favourites, recent; the active row is a tonal lift, never a coloured edge. Empty chat teaches: logo, greeting, still horizon, three example requests (explain, fresh search, study docs).

FORM: Northern lights (pick card; owner chose it over the assigned "Night broadcast"), position 1 of my ordered list. seed:7eb2226dcff92ed1 (roll degraded: catalog service unreachable).
Signature move: the aurora horizon band — Chelsy Pulse rendered as a 3 px band on the composer's top edge: still dim gradient when ready, flowing violet→lavender while generating, turquoise sweep while searching, lavender breathing while syncing, flat coral when the host is offline; still under reduced motion.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
