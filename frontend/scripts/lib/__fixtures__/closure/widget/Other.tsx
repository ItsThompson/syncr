/* A second component that loads the widget's sheet WITHOUT the shared one, which is what makes the widget's
   sheet judged against the intersection: a reference has to resolve in both contexts. */
import "./widget.css";

export function Other() {
  return null;
}
