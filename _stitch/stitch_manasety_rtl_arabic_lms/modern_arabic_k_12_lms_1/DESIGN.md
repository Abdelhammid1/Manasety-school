---
name: Modern Arabic K-12 LMS
colors:
  surface: '#f7f9fc'
  surface-dim: '#d8dadd'
  surface-bright: '#f7f9fc'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f4f7'
  surface-container: '#eceef1'
  surface-container-high: '#e6e8eb'
  surface-container-highest: '#e0e3e6'
  on-surface: '#191c1e'
  on-surface-variant: '#444651'
  inverse-surface: '#2d3133'
  inverse-on-surface: '#eff1f4'
  outline: '#757682'
  outline-variant: '#c5c5d3'
  surface-tint: '#4059aa'
  primary: '#00236f'
  on-primary: '#ffffff'
  primary-container: '#1e3a8a'
  on-primary-container: '#90a8ff'
  inverse-primary: '#b6c4ff'
  secondary: '#006689'
  on-secondary: '#ffffff'
  secondary-container: '#5bcaff'
  on-secondary-container: '#005371'
  tertiary: '#00246b'
  on-tertiary: '#ffffff'
  tertiary-container: '#00389a'
  on-tertiary-container: '#8da9ff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dce1ff'
  primary-fixed-dim: '#b6c4ff'
  on-primary-fixed: '#00164e'
  on-primary-fixed-variant: '#264191'
  secondary-fixed: '#c3e8ff'
  secondary-fixed-dim: '#78d1ff'
  on-secondary-fixed: '#001e2c'
  on-secondary-fixed-variant: '#004c68'
  tertiary-fixed: '#dbe1ff'
  tertiary-fixed-dim: '#b4c5ff'
  on-tertiary-fixed: '#00174b'
  on-tertiary-fixed-variant: '#003ea8'
  background: '#f7f9fc'
  on-background: '#191c1e'
  surface-variant: '#e0e3e6'
typography:
  display-hero:
    fontFamily: Plus Jakarta Sans
    fontSize: 40px
    fontWeight: '800'
    lineHeight: 64px
  display-hero-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 28px
    fontWeight: '800'
    lineHeight: 44px
  headline-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 52px
  headline-lg-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 24px
    fontWeight: '700'
    lineHeight: 38px
  headline-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 24px
    fontWeight: '700'
    lineHeight: 38px
  headline-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 34px
  title-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 30px
  body-lg:
    fontFamily: Nunito Sans
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 32px
  body-md:
    fontFamily: Nunito Sans
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 28px
  body-sm:
    fontFamily: Nunito Sans
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 24px
  label-lg:
    fontFamily: Nunito Sans
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 22px
  label-md:
    fontFamily: Nunito Sans
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 18px
  label-xs:
    fontFamily: Nunito Sans
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 16px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1.5rem
  margin: 2rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2.5rem
---

## Brand & Style

This design system delivers an inspiring, structured, and modern educational environment tailored natively for Arabic-speaking K-12 learning communities. Bridging pedagogical authority with childhood and teenage curiosity, the interface feels secure, engaging, and frictionless across students, educators, and parents.

### Aesthetic Direction: Modern Fluid RTL-First EdTech
- **Approach:** Modern Soft Geometric. High-clarity layouts, deep academic blues layered with sky accents, and friendly softened geometry.
- **RTL-Native Architecture:** Engineered from the foundation for Arabic reading dynamics. Information cascades naturally from right to left, with right-anchored navigation, reversed reading vectors, contextual directional icons, and typography tuned for Arabic ascenders and descenders.
- **Tone:** Authoritative yet inviting, organized, vibrant, encouraging, and distraction-free.

## Colors

The color structure is anchored in classical academic authority via deep navies, elevated by an energetic cyan-to-royal gradient representing growth, curiosity, and technological empowerment.

### Palette Roles & Values
- **Primary Navy (`#0C2461`):** Core brand foundation, primary navigation bars, active structural frames, and heavy typographic emphasis.
- **Primary Blue (`#1E3A8A`):** Core interactive states, active tabs, main action containers, and primary badges.
- **Accent Blue (`#2563EB`):** Secondary interactive accents, focused states, and active progress indicators.
- **Sky Blue (`#0099CC`):** Uplifting accent for completion statuses, gamified badges, active markers, and energetic highlights.
- **Brand Signature Gradient:** `linear-gradient(135deg, #1E3A8A 0%, #2563EB 55%, #0099CC 100%)`. Reserved for primary hero modules, certificate headers, milestone achievements, and key CTAs.
- **Surface Canvas (`#F5F7FA`):** Low-strain background tone providing soft contrast against pure white cards.
- **Surface Elevated (`#FFFFFF`):** High-priority card layers, modals, dropdown sheets, and data tables.
- **Border / Divider (`#E1E6EE`):** Structural borders, card boundaries, and quiet separators.
- **Typography Canvas:**
  - `Text Primary (#1F2937)`: Uncompromising legibility for Arabic text and titles.
  - `Text Muted (#6B7280)`: Metadata, timestamps, helper descriptions, and inactive states.
- **Functional Semantics:**
  - `Success (#10B981)`: Passed tests, submitted assignments, online attendance.
  - `Warning (#F59E0B)`: Approaching deadlines, pending parent signatures, reminders.
  - `Danger (#EF4444)`: Missing work, disciplinary alerts, system errors.

## Typography

Typographic scale balances Arabic letterform aesthetics with Latin metrics and mathematical figures. 

### Implementation Guidelines
- **Arabic UI Substitution:** In production builds, map the system headline and display tokens to "Baloo Bhaijaan 2" (weights: 400, 600, 700, 800) and body/numerals to "Nunito".
- **Vertical Metrics & Baselines:** Arabic glyphs feature tall ascenders and deep descenders. All body text enforces a relaxed line-height of 1.7 (approx. 28px on a 16px body) to eliminate glyph clipping and support fatigue-free reading across prolonged study sessions.
- **Numerals:** Support both Western Arabic numerals (1, 2, 3) and Eastern Arabic numerals (١، ٢، ٣) based on regional curriculum settings, maintaining consistent monospaced tabular figures in mathematical expressions and grade displays.

## Layout & Spacing

A fluid grid architecture engineered for natural right-to-left scanning.

### Grid & Breakpoints
- **Desktop (≥1200px):** 12-column grid, 24px (`1.5rem`) gutters, 32px (`2rem`) outer margins. Right-sidebar navigation remains fixed (width: 260px–280px), while the central learning workspace flexibly expands up to a max-width container of 1440px.
- **Tablet (768px - 1199px):** 8-column grid, 20px gutters, 24px margins. Navigation collapses to a right-anchored rail or drawer.
- **Mobile (<768px):** 4-column grid, 16px (`1rem`) gutters, 16px (`1rem`) page margins. Navigation shifts to a persistent bottom navigation bar optimized for thumb reach.

### RTL Flow Rules
- Elements prioritize horizontal flow starting from right: headers align right, badges top-left within right-aligned cards, back buttons point right (`→` in RTL context indicates previous page), and next actions point left (`←`).
- Spacing utility logic strictly follows logical CSS (`margin-inline-start`, `padding-inline-end`).

## Elevation & Depth

Visual depth combines clean surface boundaries with tinted ambient shadows reflecting the brand's core navy, creating soft elevation without visual dirtiness.

### Elevation Hierarchy
- **Level 0 (Flat Canvas):** Surface color `#F5F7FA` without shadows. Used for primary dashboard backgrounds and neutral groupings.
- **Level 1 (Card & Module Resting):** Surface `#FFFFFF`, border `1px solid #E1E6EE`, and soft brand shadow: `box-shadow: 0 4px 12px rgba(12, 36, 97, 0.05)`.
- **Level 2 (Interactive Hover & Flyouts):** Surface `#FFFFFF`, border `1px solid #E1E6EE`, elevated brand shadow: `box-shadow: 0 8px 24px rgba(12, 36, 97, 0.10)`. Used on active lesson cards, dropdown menus, and popovers.
- **Level 3 (Modals & Dialogs):** Surface `#FFFFFF`, shadow: `box-shadow: 0 20px 40px rgba(12, 36, 97, 0.16)`. Combined with a backdrop blur `backdrop-filter: blur(8px)` and deep overlay `rgba(12, 36, 97, 0.40)`.

## Shapes

The shape language utilizes approachable, contemporary curves that balance educational professionalism with child-friendly tactility.

### Corner Radius System
- **Cards & Data Modules:** 12px (`0.75rem`) border radius. Balances structural containment with gentle curvature.
- **Modals, Drawers & Large Banners:** 16px (`1rem`) border radius.
- **Pills, Badges, Search Inputs & Interactive Tags:** Fully rounded pill radius (`9999px`).
- **Interactive Controls (Inputs, Standard Buttons, Dropdown Triggers):** 10px to 12px border radius.

## Components

### Buttons
- **Primary:** Gradient fill (`linear-gradient(135deg, #1E3A8A 0%, #2563EB 55%, #0099CC 100%)`), pure white text, 12px radius, min-height 48px for touch targets. Shadow: `0 4px 14px rgba(37, 99, 235, 0.25)`. Hover elevates slightly with increased shadow saturation.
- **Secondary:** Surface `#FFFFFF`, border `1.5px solid #1E3A8A`, text `#1E3A8A`, 12px radius.
- **Tertiary / Ghost:** Transparent background, text `#1E3A8A` or `#2563EB`, background hover `#F5F7FA`.

### Input Fields & Controls
- **Text Inputs:** Height 48px, background `#FFFFFF`, border `1px solid #E1E6EE`, border-radius 10px, typography right-aligned with padding right 16px. Active focus brings a 2px outline of `#2563EB` with `0 0 0 4px rgba(37, 99, 235, 0.15)`.
- **Search Bars:** Rounded pill (`9999px`), embedded search icon anchored to the right, clear button anchored to the left.

### Checkboxes & Radio Buttons
- Checkbox dimensions 20x20px with a 6px corner radius. In active state, fill with `#1E3A8A` and clear white checkmark.
- Radio buttons 20x20px, fully circular with an internal 8px `#1E3A8A` dot upon selection.

### Chips & Badges
- Fully rounded (`9999px`), font size 12px, font-weight 600, padding `4px 12px`.
- Subject tags use soft pastel tints: Math (Blue tint: `#EFF6FF`, text `#1E3A8A`), Science (Sky tint: `#E0F2FE`, text `#0099CC`), Attendance/Success (Green tint: `#ECFDF5`, text `#059669`).

### Lesson & Course Cards
- Surface `#FFFFFF`, border `1px solid #E1E6EE`, border-radius 12px, shadow `0 8px 24px rgba(12, 36, 97, 0.06)`.
- Includes top media container with 12px top-radius, progress bar along the bottom of the thumbnail, and content block below with right-aligned titles, teacher meta, and pill tags.

### Academic Progress Bars
- Height 8px, background `#E1E6EE`, border-radius 9999px. Active bar fills from right to left using the signature linear gradient.