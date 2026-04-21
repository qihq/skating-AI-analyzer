type XpProgressBarProps = {
  value: number;
};

export default function XpProgressBar({ value }: XpProgressBarProps) {
  const width = Math.max(0, Math.min(value, 100));

  return (
    <div className="h-3 overflow-hidden rounded-full bg-gray-100">
      <div
        className="relative h-full overflow-hidden rounded-full bg-gradient-to-r from-violet-400 to-pink-400 transition-all duration-700"
        style={{ width: `${width}%` }}
      >
        <div className="animate-shimmer absolute inset-0 w-1/3 bg-white/30 skew-x-12" />
      </div>
    </div>
  );
}
