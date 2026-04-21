type UnlockCelebrationProps = {
  label: string;
};

const STAR_CLASSES = ["star-1", "star-2", "star-3", "star-4", "star-5", "star-6", "star-7", "star-8"];

export default function UnlockCelebration({ label }: UnlockCelebrationProps) {
  return (
    <div className="pointer-events-none fixed inset-0 z-40 overflow-hidden">
      <div className="absolute left-1/2 top-28 -translate-x-1/2 rounded-full bg-white px-5 py-3 text-sm font-semibold text-slate-900 shadow-floating unlock-pop">
        已点亮：{label}
      </div>
      <div className="absolute left-1/2 top-40">
        {STAR_CLASSES.map((className, index) => (
          <div
            key={className}
            className={`star-particle ${className} absolute h-3 w-3 rounded-full ${
              index % 2 === 0 ? "bg-kid-accent" : "bg-kid-secondary"
            }`}
          />
        ))}
      </div>
    </div>
  );
}
