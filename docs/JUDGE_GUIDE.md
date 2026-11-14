# Judge guide for Ash (one page)

Judges type freely on your laptop; you steer. Everything below was seen working on the local build. Read the real answer out loud; do not memorise numbers.

## 1. Open this first: the AC20 office building

Data, search "AC20", open it, press **Ask about it**. Why: it is a real building model, so counts are exact, every answer has numbered proof, and it has everything the demo needs: doors and windows, four floors, rooms, a front door, a fire-exit rule. It also works in 2D, 3D, on the phone and on the table. Check the AC20 chip above the question box before you hand over the keyboard.

## 2. Six "try asking..." nudges that work well

1. **How many doors and windows?** One answer, both counts, with numbered boxes on the plan (we saw 77 doors and 206 windows).
2. **How many doors are on the ground floor?** Shows it picks the right floor by itself.
3. **And on the first floor?** A follow-up in the same chat. The drawing swaps to the first-floor sheet without reloading.
4. **Where are the toilets?** Boxes on every floor, same numbers in 2D and 3D.
5. **What is the narrowest door width used here?** A measurement, with the door it came from.
6. **Can we remove the front door?** The what-if: the door disappears and a rule card appears (see section 3).

Backups with long answers: tile order with waste and price for the WC rooms; paint tins for 1st floor walls. Both are in `docs/DEMO_QUESTIONS.md`.

## 3. Buttons to point at after an answer

- **The little number next to a fact (citation).** Opens the drawing with numbered boxes. "Every number here is a thing you can see."
- **Visualise it.** The plan rises into a 3D building and the same numbered items glow.
- **The build slider** under the 3D view. Drag it back and forth to watch the building go up floor by floor.
- **Remove, then the rule card.** Ask "remove the front door". The door vanishes and a card says what breaks and quotes the fire-exit rule it used. Say "a violation under the model check", not "certified".
- **Pair a phone** (phone icon at the top of the chat): scan the QR. Questions asked on the laptop then open on the phone by themselves. On the phone, **Show on table** puts the building on the table with the same glowing items.

## 4. If an answer abstains or is only partial

Honesty is a feature. Say it plainly:

- "It says it can't tell, and it shows why. We would rather it say that than guess."
- "This one is a best estimate. See the confidence and the sources underneath; it never invents a rule or a source."
- "That drawing does not state it. It tells you instead of making something up."

Then offer the next step: open the sources, ask the narrower question, or switch to the model where the number is exact. Never argue with a judge about a wrong-looking number: open its citation and check it together.

## 5. Steer away from

1. **Huge uploads mid-demo.** Processing can take minutes. If a judge brings a file, upload it, then carry on with AC20 while it works, and only switch once it says Ready to use. Never imply an AC20 answer came from their file.
2. **The Barlad model before you upload.** It is the biggest one (about 100 MB) and slow to load. Keep it for the end, if at all.
3. **Edits in the middle of the build-up.** Let the building finish rising before you remove anything. Also do not start a new question while the animation is playing.

Also: two drawings give different door counts (AC20 is exact from the model, the small floor-plan image is an estimate). Always say which one is open. If something breaks, say so, name the fallback out loud, and use the recording.
