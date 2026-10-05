import "@testing-library/jest-dom/vitest";

// jsdom has no layout: scrolling an element into view does nothing there.
Element.prototype.scrollIntoView = () => undefined;
