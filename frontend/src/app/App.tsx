import { RouterProvider, createBrowserRouter } from "react-router";

import { routes } from "../routes";

/* The browser router is built once, at module scope, so a re-render cannot recreate it and
 * reset navigation state. A test builds a memory router over the same `routes`. */
const router = createBrowserRouter(routes);

export function App() {
  return <RouterProvider router={router} />;
}
