# Hologram: a judge’s guide

Open [Hologram](https://hologram-khaki.vercel.app/#/data). No login needed. Bring your own drawings and questions.

Choose **Data → Upload → Choose file**, or drop a file into the upload dialog. Upload a PDF, PNG, JPG/JPEG, DXF or IFC. Wait for **Ready**, then choose **Ask about it**. Check that your document is selected before sending a question. Processing time and available outputs depend on the file; read its status if ingestion fails or is incomplete.

Try these prompts, adapting names and levels to your drawing:

- Counts: “How many windows are shown on this floor plan?”
- Areas: “What is the net floor area of the kitchen in square metres?”
- Multi-kind: “How many windows and doors are there?”
- Take-offs: “How many square metres of floor tiles should I order for the bathrooms?”
- Location: “Where is the stair core on the ground floor?”
- Specification text: “What fire rating is specified for the doors?”
- Rule checks: “Which exits fail the available checks?” Use **Findings → select your document → Run checks** for sourced findings.
- Edits: “Remove the front door.” This hides the detected entrance in the chat’s model and preserves the original file. Try “restore the front door” afterwards.

Chat keeps earlier turns as context. After a count, try “and doors?” with the same drawing selected. Check that the follow-up still names the intended document; ambiguous references can fail.

Check every answer against your source. Click a citation to open the drawing; inspect its numbered boxes and **Sources**. For boxed object counts, **the headline count equals the numbered boxes** (row `E-25`; [implementation](../engine/answer.py)). A citation can cover several boxes. Choose **Visualise it** to inspect matching highlights in 3D when a scene is available. Item tags for scene commands are separate from answer numbering.

**Show thought process** opens the execution trace. Answer cards display incremental model cost, excluding earlier extraction and hosting. Treat “best estimate”, “low confidence” or “best-effort” as uncertainty. Text totals and forced estimates may have no object-level proof; a labelled default means readable evidence was insufficient.

The recorded [e-s200-z1 sample](../results/bench/e-s200-z1.json) has [76.47% numeric accuracy](../results/bench/e-s200-z1.json#/cells/ALL%20x%20ALL/accuracy), [0 numeric abstentions](../results/bench/e-s200-z1.json#/cells/ALL%20x%20ALL/abstained) and [0 text abstentions](../results/bench/e-s200-z1.json#/text/ALL/abstained). No abstentions does not mean all answers are correct. This sample predates later changes; see [REPORT.md](REPORT.md) for scope and other runs.

Open the site on a phone, then **History → the same chat**, to continue with cross-device live sync. **Show on table** requires the native iPhone app: place the model, view the plan-to-building build-up, then use voice to ask about or select elements. Check live arrival on the other device. Physical-device build-up, voice and delivery rehearsal remain pending in [DEMO.md](DEMO.md).

The current model chain uses Claude Sonnet 5.5 for writing/chat and Opus 5.5 for recount boxes (replacing the earlier Fable 5.2 configuration) through Runware's Anthropic-compatible `/v1/messages`; Gemini 3.1 Flash-Lite via Runware handles cheap recounts and best-effort answers. Nemotron handles routing, advisor writing and scene intent; ElevenLabs supplies TTS. Verda Nemotron VL is a slow last resort. Production has no direct Gemini or Anthropic keys; voice input can use device recognition. See [MODELS.md](MODELS.md) for exact chains and fallbacks.

Scans without reliable scale give approximate areas and quantities. Very large IFCs may time out or fail; try a smaller export. Ask in English: non-English source text may be missed or misread. Rule checks cover available rules and model properties; read quoted sources and “not checkable” notes. Missing findings do not establish compliance.
