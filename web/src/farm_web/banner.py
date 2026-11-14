"""Static HTML for the page header and the "how it works" strip.

The banner is an inline SVG of a North Dakota horizon: big sky, a low sun,
strips of wheat, canola and flax, a shelterbelt, a grain elevator and a few
sunflowers. Inline so the app stays fully offline (no image or font fetches).
"""

BANNER_HTML = """
<header class="pf-banner" role="banner">
  <svg class="pf-banner-art" viewBox="0 0 1200 260" preserveAspectRatio="xMaxYMax slice"
       aria-hidden="true" focusable="false">
    <defs>
      <linearGradient id="pf-sky" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" style="stop-color:var(--pf-sky-top)"/>
        <stop offset="0.62" style="stop-color:var(--pf-sky-mid)"/>
        <stop offset="1" style="stop-color:var(--pf-sky-low)"/>
      </linearGradient>
      <radialGradient id="pf-sun" cx="0.5" cy="0.5" r="0.5">
        <stop offset="0" style="stop-color:var(--pf-sun)" stop-opacity="0.95"/>
        <stop offset="0.45" style="stop-color:var(--pf-sun)" stop-opacity="0.35"/>
        <stop offset="1" style="stop-color:var(--pf-sun)" stop-opacity="0"/>
      </radialGradient>
      <pattern id="pf-rows" width="14" height="6" patternUnits="userSpaceOnUse"
               patternTransform="skewX(-35)">
        <rect width="14" height="6" style="fill:var(--pf-wheat)"/>
        <rect width="14" height="1.4" y="4.6" style="fill:var(--pf-wheat-deep)" opacity="0.45"/>
      </pattern>
    </defs>

    <rect width="1200" height="260" fill="url(#pf-sky)"/>
    <circle cx="905" cy="168" r="120" fill="url(#pf-sun)"/>
    <circle cx="905" cy="168" r="26" style="fill:var(--pf-sun)" opacity="0.9"/>

    <!-- high, thin prairie clouds -->
    <g fill="#ffffff" opacity="0.28">
      <ellipse cx="260" cy="58" rx="120" ry="7"/>
      <ellipse cx="330" cy="70" rx="80" ry="5"/>
      <ellipse cx="700" cy="44" rx="150" ry="6"/>
      <ellipse cx="1060" cy="84" rx="110" ry="5"/>
    </g>

    <!-- distant horizon and shelterbelt -->
    <path d="M0 176 C 180 170, 360 178, 560 172 S 940 168, 1200 174 L1200 190 L0 190 Z"
          style="fill:var(--pf-prairie-far)"/>
    <g style="fill:var(--pf-shelterbelt)">
      <path d="M90 176 q6 -14 12 0 q5 -11 10 0 q6 -16 12 0 q5 -10 10 0 q6 -13 12 0 q5 -9 10 0 z"/>
      <path d="M610 173 q5 -12 10 0 q6 -15 12 0 q5 -10 10 0 q6 -14 12 0 q5 -11 10 0 q6 -13 12 0 q5 -9 10 0 z"/>
      <path d="M1100 174 q5 -10 10 0 q6 -14 12 0 q5 -12 10 0 q6 -9 12 0 z"/>
    </g>

    <!-- grain elevator and bins -->
    <g style="fill:var(--pf-elevator)">
      <rect x="1004" y="112" width="34" height="66"/>
      <path d="M1000 112 L1021 92 L1042 112 Z"/>
      <rect x="1012" y="80" width="18" height="14"/>
      <path d="M1009 80 L1021 70 L1033 80 Z"/>
      <rect x="1038" y="140" width="22" height="38"/>
      <path d="M1036 140 L1049 132 L1062 140 Z"/>
      <rect x="1064" y="150" width="18" height="28" rx="2"/>
      <path d="M1062 150 L1073 143 L1084 150 Z"/>
      <rect x="1086" y="150" width="18" height="28" rx="2"/>
      <path d="M1084 150 L1095 143 L1106 150 Z"/>
    </g>

    <!-- crop strips: canola, flax, wheat rows -->
    <path d="M0 188 C 300 182, 700 190, 1200 182 L1200 200 C 800 206, 360 198, 0 204 Z"
          style="fill:var(--pf-canola)"/>
    <path d="M0 204 C 360 198, 800 206, 1200 200 L1200 214 C 760 222, 380 212, 0 220 Z"
          style="fill:var(--pf-flax)"/>
    <path d="M0 220 C 380 212, 760 222, 1200 214 L1200 260 L0 260 Z" fill="url(#pf-rows)"/>

    <!-- sunflowers in the foreground -->
    <g class="pf-sunflowers">
      <g transform="translate(74 196) scale(1.25)">
        <path d="M0 0 L0 46" style="stroke:var(--pf-stem)" stroke-width="3"/>
        <circle r="13" style="fill:var(--pf-petal)"/><circle r="11" style="fill:none;stroke:var(--pf-wheat-deep)" stroke-width="1.2" stroke-dasharray="2 3.2" opacity="0.6"/><circle r="6" style="fill:var(--pf-soil)"/>
      </g>
      <g transform="translate(122 206) scale(1.05)">
        <path d="M0 0 L0 46" style="stroke:var(--pf-stem)" stroke-width="3"/>
        <circle r="13" style="fill:var(--pf-petal)"/><circle r="11" style="fill:none;stroke:var(--pf-wheat-deep)" stroke-width="1.2" stroke-dasharray="2 3.2" opacity="0.6"/><circle r="6" style="fill:var(--pf-soil)"/>
      </g>
      <g transform="translate(34 210) scale(0.95)">
        <path d="M0 0 L0 46" style="stroke:var(--pf-stem)" stroke-width="3"/>
        <circle r="13" style="fill:var(--pf-petal)"/><circle r="11" style="fill:none;stroke:var(--pf-wheat-deep)" stroke-width="1.2" stroke-dasharray="2 3.2" opacity="0.6"/><circle r="6" style="fill:var(--pf-soil)"/>
      </g>
    </g>
  </svg>
  <div class="pf-banner-text">
    <p class="pf-kicker">Precision Farm &middot; grower preview</p>
    <h1>Ask your own field records.</h1>
    <p class="pf-sub">Ten seasons of your yields, costs and profit, answered in plain words.
      Every number is calculated from your files, and anything the AI adds is checked first.</p>
  </div>
</header>
"""
