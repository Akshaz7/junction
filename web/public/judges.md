# Hologram: a judge’s guide

Open [Hologram](https://hologram-khaki.vercel.app/#/data). No login needed. Bring your own drawings and questions.

Choose **Data → Upload → Choose file**, or drop a file into the upload dialog. Supported files: **PDF, PNG, JPG/JPEG, DXF and IFC**, up to **100 MiB per file**. Wait for **Ready**, then choose **Ask about it**. Check that your document is selected before sending a question.

PDF/image uploads typically became ready in **17–30 seconds in our tests**; this is a guide, not a deadline. IFC can be ready in seconds, but large models and queued uploads take longer. If processing fails or only some outputs are available, read the status before continuing.

Try these eight questions, adapting room names and levels to your drawing:

1. Counts: “How many windows are shown on this floor plan?”
2. Areas: “What is the net floor area of room 12 in square metres?”
3. Multi-kind: “How many windows and doors are there?”
4. Take-offs: “How many square metres of floor tiles should I order for the bathrooms?”
5. Location: “Where is the stair core on level 2?”
6. Specification text: “What fire rating is specified for the doors?”
7. Rule checks: “Which exits fail the available checks?” Use **Findings → select your document → Run checks** to see sourced findings.
8. Edits: “Remove the front door.” This hides the detected entrance in the chat’s model; it preserves the original file. Try “restore the front door” afterwards.

Check the answer against your source. Click a citation to open the drawing; inspect its numbered boxes and **Sources**. Box labels identify answer items; one citation can cover several boxes. Choose **Visualise it** to inspect matching numbered highlights in 3D when a scene is available. Command tags such as D1 identify model items separately.

Each answer shows its model cost; this excludes earlier drawing extraction and hosting. **Show thought process** opens the execution trace. Treat “best estimate”, “low confidence” or “best-effort” wording as uncertainty, not a measurement. Some estimates have no item-level proof; a labelled default means nothing readable was found.

Open the same site on a phone, then **History → the same chat**, to continue across devices. **Show on table** requires the native iPhone app.

Scans without a reliable scale give approximate areas and quantities. Very large IFCs may time out or fail; try a smaller export. Ask in English: non-English source text may be missed or misread. Rule checks cover only available rules and model properties; read their quoted sources and any “not checkable” notes. Missing findings do not establish compliance.
