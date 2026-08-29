const strokeColor = (score) => {
  if (score >= 70) return "#16a34a";
  if (score >= 50) return "#eab308";
  return "#dc2626";
};

export default function ConfidenceRing({
  score,
  size = 32,
  strokeWidth = 4,
}) {
  const clamped = Math.max(0, Math.min(100, Number(score) || 0));
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference - (clamped / 100) * circumference;
  const color = strokeColor(clamped);
  const center = size / 2;

  return (
    <svg
      className="confidence-ring"
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={`${Math.round(clamped)}% confidence`}
    >
      <circle
        className="confidence-ring-track"
        cx={center}
        cy={center}
        r={radius}
        fill="none"
        strokeWidth={strokeWidth}
      />
      <circle
        className="confidence-ring-value"
        cx={center}
        cy={center}
        r={radius}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={dashOffset}
        transform={`rotate(-90 ${center} ${center})`}
      />
      <text
        x="50%"
        y="50%"
        dy="0.32em"
        textAnchor="middle"
        className="confidence-ring-text"
        fill={color}
        style={{ fontSize: size / 4.2 }}
      >
        {Math.round(clamped)}%
      </text>
    </svg>
  );
}