module.exports = {
  "*.{css,scss,md,json}": ["pnpm prettier --write "],
  "*.py": ["pnpm just format "],
};
