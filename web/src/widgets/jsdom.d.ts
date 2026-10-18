// jsdom ships without types; the widget tests need only the constructor and the window.
declare module "jsdom" {
  export class JSDOM {
    constructor(html: string, options?: { runScripts?: "dangerously" | "outside-only"; pretendToBeVisual?: boolean });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    window: any;
  }
}
