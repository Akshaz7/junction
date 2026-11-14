# Stoa Pro: how to use the app

Every section is written from the real UI labels. The assistant answers "how do I / where is / can I / what can you do" questions about the app only from this file. If a feature is not here, the assistant says so and points to Help (More menu, then Help).

## Navigation
The left sidebar (bottom bar on a phone) has: Overview, Chat, Compare, Changes, Library, Data, Tools. The "More" button (three dots) holds Help. Skills and Automations are tabs inside Library. The Stoa Pro logo at the top returns to Overview. No account or login is needed.

## Upload
Open Data, then choose Upload (opens the upload dialog), then Choose file, or drop a file into the dialog. Supported formats: PDF, PNG, JPG/JPEG, DXF and IFC, up to 100 MiB per file. Wait until the document shows Ready, then choose Ask about it. PDF and image uploads usually take 17 to 30 seconds; IFC can be ready in seconds, large models take longer. "Upload a new version" on a document adds a revision of it, which Compare can then diff.

## Ask about a document
Go to Chat and type a question in the box ("Ask anything. Type @ to include a document"). Type @ to pick a document by name, or press the plus button (Add to question) to pick a document or a skill. Press Send question (the arrow) to ask. Check that the right document is selected before sending. Questions must be in English. Typical questions: counts ("How many windows and doors are there?"), areas, locations, specification text, rule checks and edits ("Remove the front door").

## Voice
The microphone button (Speak a question) next to Send turns speech into the question text. Edit it if needed, then Send.

## Citations, sources and the 2D viewer
Every answer carries numbered citations and, where it applies, numbered boxes on the drawing. Click a citation (Open citation) or Sources to open the drawing viewer with those boxes. In the viewer drag to pan, scroll or pinch to zoom, arrow keys pan, plus and minus zoom, zero fits the drawing. Fit drawing resets the view. Next and Previous drawing page move between pages. Find on sheet searches the text on the sheet. Download original source gets the uploaded file. Highlight marker and Pen annotations (toolbar above the drawing) let you mark up the page, and Undo annotation removes the last mark. Zoom in, Zoom out and Zoom level change the zoom. Close drawing viewer closes it. Show thought process under an answer opens the execution trace.

## Visualise it (3D)
Under an answer choose Visualise it, or the 3D button in the drawing viewer. The plan rises into a 3D model and the same numbered items glow. In the 3D view:
- Build slider (Build step, Previous step, Next step): scrub or play the model being built up from foundations to roof, one step at a time.
- Storeys: the minus and plus buttons (Previous storey, Next storey) move between floors; Show roof toggles the roof.
- Walk: walk through the model at eye level. Press Walk again to leave.
- Edit: opens the Edit items panel. Pick an item, then Remove it, Move it, or change the wall material. Undo reverses the last edit, and Reset puts everything back. After an edit the app shows an advice card that checks building rules.
- Findings button in the 3D toolbar shows rule findings on the model.
- Close 3D view returns to the chat.
Visualise it needs a drawing that can be shown in 3D (IFC models, and plans that were read into a plan map).

## Edits from chat
In chat you can ask "Remove the front door" or "Hide W3". The item is hidden in the chat's model only; the uploaded file is never changed. Ask "Restore W3" or choose Restore W3, or "Put it back", to bring it back. After a removal the answer says whether a rule is broken, for example the Finnish fire rule 848/2017 §33 on at least two exits.

## Findings and Run checks
Open Tools (the wrench in the sidebar). Select your document, then choose Run checks. Findings are grouped by severity (violation, suggestion, info), each quotes the rule and its source, and clicking one opens its evidence on the drawing. Only the available rules are checked; a missing finding does not prove compliance, and unchecked rules say why.

## Pair a phone
In Chat choose Pair a phone. Scan the QR code with your iPhone camera: it opens the Stoa Pro iPhone app. Chats you start on the web then open and stream on the phone with no other step. To continue a chat on another device choose History (the clock icon) and pick the chat. Close pairing closes the dialog.

## Show on table (AR)
Show on table is in the Stoa Pro iPhone app, not the web. Open an answer in the app and tap Show on table to place the model on your table in AR with the same numbered items glowing. You can scale the model up to 1:1 and walk through it. The web only tells you about it; it cannot open AR.

## Export report
Under an answer choose Export report. The dialog previews a site report; Copy as Markdown copies it. Close export report closes it.

## Share
Share (chat header) shares the current chat. History (clock icon in the chat header) lists earlier chats; pick one to reopen it. New chat (plus icon) starts a fresh chat.

## Overview
Overview is the home page: this week's changes, top findings and recent chats, each with an arrow to open the full page.

## Changes
Changes lists what changed in your documents (for example a new version). Search changes and the filters narrow the list, Refresh changes reloads it. For a new version, Open in Compare jumps to Compare.

## Compare
Compare versions: pick a drawing and two of its versions to see what moved. It compares versions of one drawing; it does not compare two different drawings (ask a question about both documents in Chat instead, using @ to pick each). Fit comparison fits both into view. Upload a new version in Data to create a second version.

## Library: Skills and Automations
Library has two tabs. Skills are saved prompts: choose a skill from the plus button in the chat box or from Library, and its prompt fills the question. Create skill adds your own. Your own skills and automations have a Delete button (Delete skill, Delete automation); built-in skills cannot be deleted. Automations run a question on a drawing on a schedule: Create automation, pick the drawing (Run on drawing) and a Schedule, and the last automation report is shown.

## Data
Data lists every document with its status (Ready, processing, failed), folders, and search. From a Ready document choose Ask about it. Documents can be searched and organised in folders.

## Help
More, then Help, shows the written guide with sample questions.

## Not available
Documents cannot be deleted in the app. Reports export as Markdown only (Copy as Markdown), not PDF. There is no teammate invitation, no password, no accounts, no billing page and no settings page. Questions in languages other than English may be missed. Features not listed in this guide are not in the app.
