# Hello Operator — TTS Script Library

All deterministic TTS responses are defined here. Variable names are used
throughout the codebase and test suite to reference these scripts. Dynamic
components are indicated with `[brackets]`.

Scripts marked **pre-rendered** are synthesized at startup and cached to audio
files. Scripts marked **runtime** are synthesized on demand via live Piper
(they contain dynamic components or are too situational to pre-render).

---

## Operator — Idle Flow

### `SCRIPT_OPERATOR_OPENER`
**Pre-rendered** — spoken once per session, at the first menu prompt after handset lift only
> "Operator."

### `SCRIPT_GREETING`
**Pre-rendered** — spoken after `SCRIPT_OPERATOR_OPENER` on first prompt; repeated alone on subsequent prompts
> "How may I direct your call?"

### `SCRIPT_EXTENSION_HINT`
**Pre-rendered**
> "If you know your party's extension, please dial it now. Otherwise, stay on the line and I'll connect you shortly."

### `SCRIPT_IDLE_MENU`
**Runtime** (dynamic — only available categories announced)
> "I have the following exchanges available. For playlists, dial one. For artists, dial two. For genres, dial three. To place a trunk call to the general exchange, dial four."

---

## Operator — Playing Flow

### `SCRIPT_PLAYING_GREETING`
**Runtime** (contains media name) — spoken after `SCRIPT_OPERATOR_OPENER` on first prompt; repeated alone on subsequent prompts
> "Your call with [media name] is currently in progress."

### `SCRIPT_PLAYING_MENU_DEFAULT`
**Pre-rendered** (playing, not on hold, not last track)
> "To place your call on hold, dial one. To transfer to the next party, dial two. To disconnect your call, dial three. To reach a new party, dial zero."

### `SCRIPT_PLAYING_MENU_ON_HOLD`
**Pre-rendered** (on hold, not last track)
> "To resume your call, dial one. To transfer to the next party, dial two. To disconnect your call, dial three. To reach a new party, dial zero."

### `SCRIPT_PLAYING_MENU_LAST_TRACK`
**Pre-rendered** (playing, not on hold, last track)
> "To place your call on hold, dial one. To disconnect your call, dial three. To reach a new party, dial zero."

### `SCRIPT_PLAYING_MENU_ON_HOLD_LAST_TRACK`
**Pre-rendered** (on hold, last track)
> "To resume your call, dial one. To disconnect your call, dial three. To reach a new party, dial zero."

---

## Navigation

### `SCRIPT_NOT_IN_SERVICE`
**Pre-rendered** (invalid digit or no results)
> "I'm sorry, that number is not in service. Please check the number and try again."

### `SCRIPT_SERVICE_DEGRADATION`
**Pre-rendered**
> "I beg your pardon — we're experiencing some difficulty on the line. One moment please."

### `SCRIPT_MISSED_CALL`
**Runtime** (contains assistant number)
> "You have a missed call from your assistant. To reach them, dial [assistant number]."

---

## Browse

### `SCRIPT_BROWSE_PROMPT_PLAYLIST`
**Pre-rendered**
> "Please dial the first letter of your playlist's name."

### `SCRIPT_BROWSE_PROMPT_ARTIST`
**Pre-rendered**
> "Please dial the first letter of your artist's name."

### `SCRIPT_BROWSE_PROMPT_GENRE`
**Pre-rendered**
> "Please dial the first letter of your genre."

### `SCRIPT_BROWSE_PROMPT_ALBUM`
**Pre-rendered**
> "Please dial the first letter of your album's name."

### `SCRIPT_BROWSE_PROMPT_NEXT_LETTER`
**Pre-rendered**
> "I have quite a few parties on that exchange. Please dial the next letter of your party's name to narrow the connection."

### `SCRIPT_BROWSE_LIST_INTRO`
**Runtime** (contains count)
> "I have [n] parties on the line. [option list]"

### `SCRIPT_BROWSE_AUTO_SELECT`
**Runtime** (contains name)
> "One moment — I have exactly one match. Connecting you to [name] now."

---

## Artist Submenu

### `SCRIPT_ARTIST_SUBMENU`
**Runtime** (contains artist name; album option conditional)
> "To speak to [artist], dial one. [For a particular album, dial two.]"

### `SCRIPT_ARTIST_SINGLE_ALBUM`
**Runtime** (contains album name)
> "To call [album name], dial one."

---

## Final Selection

### `SCRIPT_CONNECTING`
**Runtime** (contains digits and media name)
> "Thank you for your patience. I'm connecting your call to [digit] [digit] [digit], [digit] [digit] [digit] [digit] — [media name]. Please hold."

### `SCRIPT_SHUFFLE_CONNECTING`
**Pre-rendered** — spoken after the user selects the shuffle/general-exchange option
> "One moment, please — I'm putting you through to the general exchange. Enjoy your call!"

---

## Radio

### `SCRIPT_RADIO_CONNECTING`
**Runtime** (contains station name and frequency)
> "Thank you for your patience. Tuning in to [station name] — [frequency] megahertz. Please stand by."

### `SCRIPT_RADIO_PLAYING_GREETING`
**Runtime** (contains station name and frequency)
> "You are currently tuned to [station name] on [frequency] megahertz."

### `SCRIPT_RADIO_PLAYING_MENU`
**Pre-rendered**
> "To disconnect your call, dial three. To reach a new party, dial zero."

---

## Error States

### `SCRIPT_PLEX_FAILURE`
**Pre-rendered**
> "I'm sorry, our long-distance exchange appears to be temporarily out of service. We apologize for the inconvenience."

### `SCRIPT_DB_FAILURE`
**Pre-rendered**
> "I'm sorry, our directory appears to be temporarily unavailable. The switchboard is experiencing an internal fault."

### `SCRIPT_RETRY_PROMPT`
**Pre-rendered** (used for both Plex and DB failures)
> "If you'd like me to try the exchange again, dial one. Otherwise, you may replace your handset and try your call again later."

### `SCRIPT_NO_CONTENT`
**Pre-rendered**
> "We're sorry. There are no parties available on this exchange at this time. Please replace your handset."

### `SCRIPT_TERMINAL_FALLBACK`
**Pre-rendered**
> "We're sorry. Your call cannot be completed as dialed. Please replace your handset and try again later."

---

## Diagnostic Assistant

### `SCRIPT_ASSISTANT_GREETING`
**Runtime** (contains time of day)
> "Good [morning/afternoon/evening], this is the operator's assistant. Let me pull up your account now."

### `SCRIPT_ASSISTANT_ALL_CLEAR`
**Pre-rendered**
> "Everything is running just beautifully, I'm happy to report. No messages, no trouble on the lines. You're all set, chief. I'll let you get back to it — toodle-oo!"

### `SCRIPT_ASSISTANT_STATUS_INTRO`
**Pre-rendered**
> "I do have a few things here for you. Let me see now..."

### `SCRIPT_ASSISTANT_MESSAGE_OPTIONS`
**Runtime** (contains counts and dynamic options)
> "I have [n] warning[s] and [n] error[s] in the queue. For warnings, dial one. For errors, dial two. Or dial zero to go back to the switchboard."

### `SCRIPT_ASSISTANT_READING_INTRO`
**Runtime** (contains count and `ASSISTANT_MESSAGE_PAGE_SIZE`)
> "All right, here we go. I have [n] message[s] for you. I'll read you the first [ASSISTANT_MESSAGE_PAGE_SIZE]."

### `SCRIPT_ASSISTANT_CONTINUE_PROMPT`
**Runtime** (contains `ASSISTANT_MESSAGE_PAGE_SIZE`)
> "That's [ASSISTANT_MESSAGE_PAGE_SIZE]. Shall I go on? Dial one to continue, or dial zero to go back to the switchboard."

### `SCRIPT_ASSISTANT_END_OF_MESSAGES`
**Pre-rendered**
> "And that's the last of them. Is there anything else I can help you with?"

### `SCRIPT_ASSISTANT_NAVIGATION`
**Pre-rendered**
> "To hear that again, dial one. For the previous menu, dial nine. To go back to the switchboard, dial zero."

### `SCRIPT_ASSISTANT_VALEDICTION_CLEAR`
**Pre-rendered**
> "Right then, I'll put you back through to the switchboard. Have a wonderful day!"

### `SCRIPT_ASSISTANT_VALEDICTION_MESSAGES`
**Pre-rendered**
> "I'll put you back through now. Do give a shout if you need anything else!"

### `SCRIPT_ASSISTANT_REFRESH_SUCCESS`
**Pre-rendered**
> "All done! I've gone ahead and updated all my records from the exchange. Everything's shipshape."

### `SCRIPT_ASSISTANT_REFRESH_FAILURE`
**Pre-rendered**
> "I'm afraid I had some trouble reaching the exchange just now. My records are unchanged. You might try again in a moment, dear."

### `SCRIPT_ASSISTANT_REFRESH_PROMPT`
**Runtime** (contains digit for refresh option)
> "To refresh my records from the exchange, dial [n]."
