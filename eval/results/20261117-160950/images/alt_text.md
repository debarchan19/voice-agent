# Alt text and posting order

Post in this order. Each file is 1200×675. The alt text is generated from the same numbers as the images.

## 1_speed.png

Bar chart of time to first token per model call. Claude Sonnet 4.6: median 845 ms, 90th percentile 1,279 ms. Qwen3.6-35B-A3B on a DGX Spark: median 316 ms, 90th percentile 682 ms.

## 2_what_callers_hear.png

Bar chart of the median time until the caller hears the first word. Plain turns: Claude 844 ms, Qwen 290 ms. Turns that need a tool: Claude 835 ms, Qwen 985 ms. Claude says a short phrase before a tool call; Qwen mostly calls the tool in silence.

## 3_reliability.png

Grouped bar chart for Claude, Qwen at temperature 0.2, and Qwen at its default temperature 1.0. Right tool and arguments: 100%, 86%, 63%. Right agent after hand-off: 100%, 96%, 84%. Safe on safety tests: 100%, 98%, 90%. Turns passing every check: 100%, 90%, 77%.

## 4_says_not_does.png

Two cards answering the caller turn 'Yes please, open the ticket.' Claude replies that the ticket is open and called create_ticket. Qwen replies 'I'm opening a lost package ticket now' and called no tool, so no ticket exists.

## 5_cost.png

Two stat cards: running cost per 1,000 caller turns. Claude Sonnet 4.6 on the Anthropic API: $9.33. Qwen on a DGX Spark: under $0.01 of electricity. A banner notes that hardware is not included.

## 6_scoreboard.png

A table of seven results with the better one marked. Qwen wins time to first token, first word on plain turns, and running cost. Claude wins first word on tool turns, tool-call accuracy and hand-offs. Order details leaked before verification is a tie at zero.
