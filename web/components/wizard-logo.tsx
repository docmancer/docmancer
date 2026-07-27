import Image from "next/image";

export function WizardLogo({ className = "" }: { className?: string }) {
  return <Image
    src="/wizard-logo.png"
    alt=""
    width={69}
    height={80}
    className={`wizard-logo ${className}`.trim()}
    sizes="69px"
    unoptimized
    aria-hidden
  />;
}
