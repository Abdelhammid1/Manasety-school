---
name: Modern Arabic K-12 LMS
colors:
  surface: '#f7f9fc'
  surface-dim: '#d8dadd'
  surface-bright: '#f7f9fc'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f4f7'
  surface-container: '#edf0f5'
  surface-container-high: '#e5e9f0'
  surface-container-highest: '#dce1eb'
  primary: '#1e3a8a'
  primary-container: '#dbeafe'
  secondary: '#2563eb'
  secondary-container: '#eff6ff'
  tertiary: '#0099cc'
  tertiary-container: '#e0f2fe'
  navy: '#0c2461'
  navy-surface: '#0c2461'
  navy-active: rgba(255,255,255,0.06)
  on-surface: '#0f172a'
  on-surface-variant: '#475569'
  outline: '#cbd5e1'
  outline-variant: '#e2e8f0'
  sidebar-icon: '#dbe7ff'
  modal-backdrop: rgba(12, 36, 97, 0.40)
  inverse-surface: '#2d3133'
  inverse-on-surface: '#eff1f4'
  surface-tint: '#4059aa'
  on-primary: '#ffffff'
  on-primary-container: '#90a8ff'
  inverse-primary: '#b6c4ff'
  on-secondary: '#ffffff'
  on-secondary-container: '#fefcff'
  on-tertiary: '#ffffff'
  on-tertiary-container: '#42b7eb'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dce1ff'
  primary-fixed-dim: '#b6c4ff'
  on-primary-fixed: '#00164e'
  on-primary-fixed-variant: '#264191'
  secondary-fixed: '#dbe1ff'
  secondary-fixed-dim: '#b4c5ff'
  on-secondary-fixed: '#00174b'
  on-secondary-fixed-variant: '#003ea8'
  tertiary-fixed: '#c3e8ff'
  tertiary-fixed-dim: '#78d1ff'
  on-tertiary-fixed: '#001e2c'
  on-tertiary-fixed-variant: '#004c68'
  background: '#f7f9fc'
  on-background: '#191c1e'
  surface-variant: '#e0e3e6'
typography:
  font-family-base: '''Baloo Bhaijaan 2'', ''Plus Jakarta Sans'', system-ui, sans-serif'
  font-family-numbers: '''Nunito'', ''Plus Jakarta Sans'', sans-serif'
  display-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 40px
    fontWeight: '700'
    lineHeight: 52px
  display-lg-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 30px
    fontWeight: '700'
    lineHeight: 40px
  headline-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 42px
  headline-lg-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 26px
    fontWeight: '700'
    lineHeight: 34px
  headline-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  headline-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  title-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 26px
  body-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22px
  label-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
  label-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 18px
  label-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 16px
components:
  sidebar/expanded:
    width: 280px
    background: '#0c2461'
    item-padding: 12px 16px
    icon-size: 20px
    label-display: inline-block
    transition: all 220ms cubic-bezier(0.4, 0, 0.2, 1)
  sidebar/mini:
    width: 72px
    background: '#0c2461'
    icon-size: 20px
    label-display: none
    active-border: '3px solid #2563eb'
    active-bg: rgba(255, 255, 255, 0.06)
    tooltip: floating left (RTL) with arrow
    transition: all 220ms cubic-bezier(0.4, 0, 0.2, 1)
  sidebar/mobile-drawer:
    width: 280px
    position: fixed
    right: '0'
    transform: translateX(100%)
    overlay: rgba(12, 36, 97, 0.5)
  sidebar/hidden:
    display: none
  modal/confirm-standard:
    max-width: 720px
    border-radius: 16px
    backdrop-filter: blur(8px)
    backdrop-color: rgba(12, 36, 97, 0.40)
  modal/confirm-split-view:
    max-width: 960px
    border-radius: 16px
    backdrop-filter: blur(8px)
    backdrop-color: rgba(12, 36, 97, 0.40)
  focus-mode/quiz:
    sidebar: hidden
    header: minimal progress bar + exit confirmation
  focus-mode/auth:
    sidebar: hidden
    layout: centered card or 50/50 split
  focus-mode/error:
    sidebar: hidden
    layout: centered illustration + action button
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1.5rem
  margin: 1.5rem
  gutter-sm: 1rem
  margin-sm: 1rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2rem
---

