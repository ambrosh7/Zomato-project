---
name: Nocturne Culinary Guide
colors:
  surface: '#121316'
  surface-dim: '#121316'
  surface-bright: '#38393c'
  surface-container-lowest: '#0d0e11'
  surface-container-low: '#1b1b1f'
  surface-container: '#1f1f23'
  surface-container-high: '#292a2d'
  surface-container-highest: '#343538'
  on-surface: '#e3e2e6'
  on-surface-variant: '#e3beb7'
  inverse-surface: '#e3e2e6'
  inverse-on-surface: '#303034'
  outline: '#aa8983'
  outline-variant: '#5b403b'
  surface-tint: '#ffb4a5'
  primary: '#ffb4a5'
  on-primary: '#650a00'
  primary-container: '#ff5a3c'
  on-primary-container: '#5c0800'
  inverse-primary: '#b5250c'
  secondary: '#ffb4a4'
  on-secondary: '#601304'
  secondary-container: '#822c19'
  on-secondary-container: '#ff9f8a'
  tertiary: '#f0c04d'
  on-tertiary: '#3f2e00'
  tertiary-container: '#b78c1a'
  on-tertiary-container: '#392900'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#ffdad3'
  primary-fixed-dim: '#ffb4a5'
  on-primary-fixed: '#3f0400'
  on-primary-fixed-variant: '#8e1300'
  secondary-fixed: '#ffdad3'
  secondary-fixed-dim: '#ffb4a4'
  on-secondary-fixed: '#3d0600'
  on-secondary-fixed-variant: '#7f2a17'
  tertiary-fixed: '#ffdf9d'
  tertiary-fixed-dim: '#f0c04d'
  on-tertiary-fixed: '#251a00'
  on-tertiary-fixed-variant: '#5b4300'
  background: '#121316'
  on-background: '#e3e2e6'
  surface-variant: '#343538'
typography:
  display-masthead:
    fontFamily: Playfair Display
    fontSize: 56px
    fontWeight: '600'
    lineHeight: 64px
    letterSpacing: -0.02em
  display-masthead-mobile:
    fontFamily: Playfair Display
    fontSize: 36px
    fontWeight: '600'
    lineHeight: 44px
    letterSpacing: -0.01em
  headline-lg:
    fontFamily: Playfair Display
    fontSize: 40px
    fontWeight: '500'
    lineHeight: 48px
    letterSpacing: -0.02em
  headline-lg-mobile:
    fontFamily: Playfair Display
    fontSize: 28px
    fontWeight: '500'
    lineHeight: 36px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Playfair Display
    fontSize: 24px
    fontWeight: '500'
    lineHeight: 32px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Playfair Display
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 24px
  body-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
  label-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: 0.02em
  label-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.04em
  label-meta:
    fontFamily: Plus Jakarta Sans
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 14px
    letterSpacing: 0.08em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1.5rem
  gutter-mobile: 1rem
  margin: 3rem
  margin-mobile: 1.25rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2.5rem
  space-2xl: 4rem
---

## Brand & Style

The design system embodies a discreet, midnight editorial atmosphere tailored for discerning epicures exploring Bangalore’s neighborhood culinary scenes—from Indiranagar's speakeasies to Koramangala's craft kitchens and Malleshwaram's heritage nooks. It avoids the neon glow and aggressive promotional badges of transactional food aggregators. Instead, it evokes the sensory warmth of dim dining rooms, heavy linen, ambient candlelight, and intimate late-night conversations.

The aesthetic fuses **Editorial Sophistication** with **Nocturnal Minimalism**. Layouts feel curated like high-end food journals, relying on deep near-black foundations, generous atmospheric negative space, hairline structural framing, and a restrained terracotta ember glow. Interactions must feel silent, smooth, and tactile—eschewing playful bounces in favor of purposeful, weighted transitions.

## Colors

The palette operates under a native dark-first paradigm designed to minimize glare during late-evening exploration while elevating culinary imagery.

- **Background Canvas (`#0B0C0F`)**: Deepest void black with a faint cool undertone. Used for global application canvas and backdrop sceneries.
- **Surface Foundations (`#14161C` / `#1C1F28`)**: Subtle dark slate tiers that establish depth without relying on stark drop shadows. `#14161C` hosts cards and list sections; `#1C1F28` defines hovered elements, inner wells, and active selections.
- **Hairline Framing (`#2A2E38`)**: Low-contrast architectural line work that preserves structured editorial columns without breaking nocturnal immersion.
- **Primary Accent (`#FF5A3C`)**: A warm vermilion/terracotta reminiscent of wood-fired hearths and neon street cart reflections. Used sparingly for interactive focal points, selected states, and AI recommendations.
- **Secondary Accent (`#FF8A70`)**: Soft salmon tone for muted tags, highlights, and secondary interactive states.
- **Semantic Anchors**:
  - `Gold (#F5C451)`: Reserved exclusively for Michelin/curator stars, critique tiers, and neighborhood awards.
  - `Success (#3DDC97)`: Table openings, live seat confirmations, and neighborhood transit statuses.
  - `Danger (#FF6B7A)`: Fully booked warnings and error states.

## Typography

The typographic hierarchy pairs the literary elegance of **Playfair Display** with the pristine mechanical legibility of **Plus Jakarta Sans**.

- **Editorial Serifs (`Playfair Display`)**: Used deliberately for venue naming, curated critique summaries, neighborhood guides, and hero narrative intros. It gives individual restaurants personality, elevating them from "database entries" to curated culinary experiences.
- **Structural San-Serif (`Plus Jakarta Sans`)**: Delivers high-density utility for opening hours, geo-coordinates, cuisine taxonomies, dietary tokens, and AI prompt interactions. 
- **Tracking & Proportion**: Headlines employ subtle negative tracking to mimic bespoke typesetting. Meta labels and neighborhood tags feature expanded tracking (`0.04em` to `0.08em`) with uppercase styling for immediate visual anchors across dense nighttime cards.

## Layout & Spacing

The layout is built around a structured 12-column grid system (desktop) collapsing into 6 columns (tablet) and 4 columns (mobile), using fixed margins combined with fluid columns.

- **Desktop (1200px+)**: 12 columns, `1.5rem` (24px) gutters, and `3rem` (48px) safe canvas margin. Asymmetrical column spreads (e.g., 5-column restaurant hero vs. 7-column neighborhood commentary) create an editorial rhythm.
- **Tablet (768px - 1199px)**: 6 columns, `1.25rem` (20px) gutters, and `2rem` (32px) margins. Search and filter rails collapse into sliding lateral sheets.
- **Mobile (<768px)**: 4 columns, `1rem` (16px) gutters, and `1.25rem` (20px) outer margins. Cards occupy full width or run in edge-to-edge peek carousels with snap behaviors.
- **Vertical Rhythm**: A strict 4px/8px incremental rhythm governs all stacking context. Major content sections separate with `space-2xl` (64px) to retain an uncluttered, high-end journal aesthetic.

## Elevation & Depth

This design system avoids heavy blurred drop shadows that muddy near-black palettes. Instead, depth is articulated through **Tonal Layering**, **Hairline Framing**, and **Backdrop Diffusion**:

- **Ground Level (Canvas)**: `#0B0C0F` acts as the unlit bedrock.
- **Level 1 (Card & Module)**: `#14161C` outlined with a crisp `1px solid #2A2E38` border. This separation creates razor-sharp structural boundaries without diffuse visual noise.
- **Level 2 (Popovers, Flyouts, Navigation Rails)**: `#1C1F28` overlaid with `backdrop-filter: blur(16px)` and low-opacity hairpins (`rgba(255, 255, 255, 0.08)`).
- **The Terracotta Ember Halo**: Active selections, focused AI inputs, and featured recommendation badges generate a tightly confined radial glow: `box-shadow: 0 0 24px rgba(255, 90, 60, 0.15)`.
- **Grain Overlay**: A persistent procedural noise texture (2-3% opacity, SVG filter) is fixed across surfaces to evoke the tooth of archival fine-print paper.

## Shapes

The shape system employs deliberate geometric contrast to separate content containers from interactive drivers:

- **Cards & Panes**: Enforced at `1rem` (16px) border radius (`radius-card`). This creates an architectural, confident corner radius that softens the grid without feeling bubbly.
- **Inputs & Text Areas**: Grounded at `0.75rem` (12px) border radius (`radius-input`), visually anchoring search fields and conversational AI prompts.
- **Buttons, Badges & Chips**: Strict full-pill geometry (`999px`). The contrast between structured rectangular cards and sleek, pill-shaped triggers immediately clarifies interactive affordance.

## Components

### Buttons
- **Primary Pill**: Filled with `#FF5A3C`, text in `#0B0C0F` (bold, Plus Jakarta Sans), padding `12px 24px`. On hover, transitions background to `#FF8A70` with a subtle `0 0 16px rgba(255, 90, 60, 0.25)` ambient glow.
- **Secondary / Ghost Pill**: Transparent fill, hairline border `1px solid #2A2E38`, text in `#F4F1EA`. On hover, background shifts to `#1C1F28` and border illuminates to `rgba(255, 255, 255, 0.2)`.
- **Icon Actions**: 40px circular buttons, background `#14161C`, border `1px solid #2A2E38`, centered stroke icon in `#9AA3B2`.

### Chips & Filter Pills
- **State Neutral**: Background `#14161C`, border `1px solid #2A2E38`, text `#9AA3B2` in `label-meta` (uppercase, tracking +0.08em), height 32px, padding `0 14px`.
- **State Active**: Background `#FF5A3C`, border `1px solid #FF5A3C`, text `#0B0C0F` font weight 600.
- **Neighborhood Badges**: Background `#1C1F28`, hairline `rgba(255, 255, 255, 0.06)`, text `#F4F1EA` with leading 6px terracotta dot indicator.

### Input Fields & AI Prompt Bar
- **Architecture**: `0.75rem` (12px) radius, background `#14161C`, border `1px solid #2A2E38`, text `#F4F1EA`. Placeholder styled in `#9AA3B2` at 60% opacity.
- **Focus State**: Hairline border shifts to `#FF5A3C` with a matching `0 0 0 1px #FF5A3C` ring. No bulky multi-pixel glow.
- **Prompt Action Hub**: Features an embedded trailing pill trigger with an understated terracotta gradient icon and a keyboard shortcut tag (`⌘K`) in muted monospace.

### Restaurant & Story Cards
- **Structure**: Surface `#14161C`, radius `16px`, enclosed in `1px solid #2A2E38`. 
- **Media Presentation**: Aspect ratio 16:10 with high-contrast culinary photo. Subtle top-to-bottom dark gradient overlay (`rgba(11,12,15,0) 50%` to `#14161C 100%`) creating unified text integration.
- **Content Stacking**:
  - Upper: Neighborhood micro-pill (`Indiranagar • 12th Main`) + Gold rating token (`#F5C451 ★ 4.9`).
  - Title: Playfair Display `headline-md` in `#F4F1EA`.
  - Body: 2-line AI tasting digest in `#9AA3B2`.
  - Footer: Vibe pills (`Craft Cocktails`, `Late Kitchen 1:30 AM`) in muted surface-2 containers.

### Checkboxes & Radios
- **Checkboxes**: 18px rounded square (4px radius), border `1.5px solid #2A2E38`, background `#14161C`. Active state fills with `#FF5A3C` using a crisp `#0B0C0F` checkmark.
- **Radio Buttons**: 18px circle, border `1.5px solid #2A2E38`, active state reveals an inset 6px dot of `#FF5A3C`.

### Lists & Curated Collections
- Clean tabular rows separated strictly by `1px solid #2A2E38`.
- Left-aligned serif restaurant index number (e.g., `01`, `02`) in `#9AA3B2` styled with monospaced tabular figures, transitioning to `#FF5A3C` on row hover.