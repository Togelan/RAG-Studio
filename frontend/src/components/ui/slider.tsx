import { Slider as SliderPrimitive } from "radix-ui"

import { cn } from "../../lib/utils"

export function Slider({
  "aria-label": ariaLabel,
  className,
  ...props
}: React.ComponentProps<typeof SliderPrimitive.Root>): React.JSX.Element {
  return (
    <SliderPrimitive.Root className={cn("rs-slider", className)} {...props}>
      <SliderPrimitive.Track className="rs-slider__track">
        <SliderPrimitive.Range className="rs-slider__range" />
      </SliderPrimitive.Track>
      <SliderPrimitive.Thumb aria-label={ariaLabel} className="rs-slider__thumb" />
    </SliderPrimitive.Root>
  )
}
