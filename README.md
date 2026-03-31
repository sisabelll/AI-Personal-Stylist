# AI Personal Stylist

> A multi-agent AI system that helps you discover and develop your personal style — not just what to wear today, but who you want to become.

---

## Why This Exists

Personal stylists are one of the most impactful yet inaccessible services in the world. They shape how people show up, how they're perceived, and how they feel about themselves — but they're almost exclusively available to celebrities and the wealthy.

This project is an attempt to change that.

Most AI fashion tools solve the wrong problem. They tell you what to wear given what you already own. This system is built for people who don't yet know their style — who want to *develop* an aesthetic identity, not just execute one. It sits at the intersection of professional styling advice, visual inspiration, and long-term taste development.

The goal: a stylist in your pocket, for everyone.

---

## Architecture

This is not a chatbot wrapper. It's a multi-agent reasoning pipeline where each agent has a distinct role in the styling process.

### Request Pipeline

```
User input → Interpreter → Stylist → Editor Loop → Refiner → Response
```

| Agent | Role |
|---|---|
| **Interpreter** | Parses user input into a clean `StyleState` object. Resolves contradictions (e.g. "actually a romper" replaces "dress", not appends to it). Extracts occasion, constraints, and intent. |
| **Stylist** | Core reasoning agent. Generates outfit recommendations using fashion knowledge, user context, and signals from the knowledge base. |
| **Editor Loop** | Self-critique layer. Evaluates Stylist output against styling principles and iterates up to N times before passing output downstream. |
| **Refiner** | Final polish. Adjusts tone, clarity, and voice so recommendations feel like advice from a human stylist, not a language model. |

### Autonomous Background Agents

These run on a schedule and continuously build the system's knowledge base — independent of user requests.

| Agent | Role |
|---|---|
| **Trend Agent** | Researches current fashion trends. Injects live style signals into the Stylist's context so recommendations stay culturally current. |
| **Inspiration Agent** | Collects imagery from style icons and brands. Builds a visual inspiration corpus that powers the inspiration board and grounds recommendations in real fashion references. |

### Knowledge Base

A vector store (trends · inspiration · style signals) that the Stylist queries at inference time. Background agents write to it continuously; the request pipeline reads from it. This is the RAG layer that makes the system's knowledge live rather than static.

---

## Key Design Principles

**1. Grounded in real styling theory**
Human stylists don't freestyle — they apply established frameworks. This system is built on the same foundations:

- **Color season theory** — identifying whether a user is a warm/cool/neutral season and filtering recommendations to their palette
- **Body essence type theory** — matching silhouettes, fabrics, and aesthetics to a person's physical and energetic presence, not just their measurements
- **Color harmony principles** — ensuring outfits work as a coherent visual system, not just individual pieces
- **Silhouette and proportion theory** — balancing fit across the body with intention

The Rule Engine encodes these frameworks so the Stylist's output is always grounded in theory, not just pattern matching on training data. This is what separates professional styling advice from generic fashion tips.

**2. Visual grounding**
Fashion is inherently visual. Text-only styling advice is insufficient. The inspiration board gives users a way to explore aesthetics visually, develop taste, and align recommendations with real fashion references — something most AI fashion tools skip entirely.

**3. Context awareness**
Recommendations are aware of where you are: your city, the weather, and the cultural context of your location. A recommendation for NYC in February is different from one for LA in October. If you're visiting Paris for a week, the system doesn't just account for the weather — it pulls what's trending in that city, what locals are wearing, and what the cultural aesthetic of that place calls for. The Trend Agent is city-aware, so you're not just dressed appropriately for the climate: you're dressed like you belong there.

**4. Long-term style evolution**
The goal isn't a single outfit. It's helping users build a coherent aesthetic identity over time — discovering what resonates, understanding why, and gradually developing a wardrobe with intention.

---

## Current Stack

| Layer | Technology |
|---|---|
| Frontend | Streamlit |
| Agent orchestration | Python |
| LLM backbone | Claude (Anthropic) |
| Inspiration board | Custom UI with image curation pipeline |
| Knowledge base | Vector store (in progress) |

---

## Features (Current MVP)

- **Styling chat** — conversational interface with multi-agent reasoning pipeline
- **Inspiration board** — Pinterest-style visual discovery from style icons and brands
- **Context-aware recommendations** — city and weather-aware styling advice
- **Onboarding flow** — collects style preferences, aesthetic references, and lifestyle context

---

## Roadmap

### Near-term
- [ ] Trend Agent — live fashion trend ingestion
- [ ] Knowledge base — vector store with RAG retrieval for Stylist
- [ ] Editor Loop — iterative self-critique before final output
- [ ] Rule Engine — enforce color harmony, silhouette balance, layering logic
- [ ] Improved inspiration board — deduplication, broken URL filtering, cleaner card layout

### Longer-term
- [ ] Digital wardrobe — upload and organize your closet
- [ ] Multi-city travel styling — packing and outfit planning across climates
- [ ] Wardrobe gap analysis — identify what's missing for your lifestyle
- [ ] Style evolution tracking — longitudinal taste development over time

---

## Project Status

Active development. Core agent pipeline (Interpreter → Stylist → Refiner) is running. Inspiration board prototype is live. Background agents and knowledge base are in progress.

---

## About

Built by Isabel Lee — software engineer and CS + Cognitive Science graduate from Penn. Currently at JPMorgan Chase with experience in LLM engineering and data engineering in Payments Technology.

This project is both a personal passion and a technical exploration of what agentic AI systems can do when applied to a domain that genuinely matters to people.

