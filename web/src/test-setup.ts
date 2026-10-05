import "@testing-library/jest-dom/vitest";

// jsdom has no layout: scrolling an element into view does nothing there. Chrome returns
// a promise from it, which an effect must not hand back to React; so does this stand-in.
Element.prototype.scrollIntoView = (() => Promise.resolve()) as unknown as () => void;
