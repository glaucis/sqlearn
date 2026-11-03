// commitlint.config.mjs - this repository's commit conventions, as commitlint
// checks them. The git hook .githooks/commit-msg hands every commit message to
// commitlint with this file, and refuses the commit on any rule at level 2. A
// rule at level 1 is printed as a warning and never refuses.
//
// This file IS the conventions, and the one place they are kept. Change a rule
// here and the next commit is held to it.
//
// It has no `extends` and names no package, on purpose. commitlint is installed
// globally and this repository holds no package.json and no node_modules, so
// anything named here would have to be found there and would not be. Every rule
// below is one commitlint ships with. A rule of this repository's own can join
// later, in this same file, as a function under `plugins`.
//
// Levels: 0 off, 1 warning, 2 error. Rules: https://commitlint.js.org/reference/rules

export default {
  // The last line of a refusal. A path and not an address: it is printed for
  // whoever was refused to open, and nothing fetches it.
  helpUrl: 'commitlint.config.mjs at the repository root holds the rules',

  // Off, so that a `fixup!`, `squash!` or `amend!` subject is held to the rules
  // like any other. Left on, commitlint passes those subjects unread, and merge
  // and revert subjects with them.
  defaultIgnores: false,

  // How a header is read. Written out because the parser commitlint falls back
  // on has no `!` in its pattern, and reads `feat(auth)!: subject` as a header
  // with no type and no subject at all. These are the options the
  // conventionalcommits preset uses, given here because a preset named as a
  // package is something a global install cannot find.
  parserPreset: {
    parserOpts: {
      headerPattern: /^(\w*)(?:\((.*)\))?!?: (.*)$/,
      breakingHeaderPattern: /^(\w*)(?:\((.*)\))?!: (.*)$/,
      headerCorrespondence: ['type', 'scope', 'subject'],
      noteKeywords: ['BREAKING CHANGE', 'BREAKING-CHANGE'],
    },
  },

  rules: {
    // --- the header: `type(scope): subject` --------------------------------
    // A header that is not of that shape at all parses as no type and no
    // subject, and is refused by the two `-empty` rules.
    'type-empty': [2, 'never'],
    'subject-empty': [2, 'never'],
    'type-case': [2, 'always', 'lower-case'],
    'type-enum': [
      2,
      'always',
      ['feat', 'fix', 'perf', 'refactor', 'build', 'test', 'ci', 'docs',
       'style', 'chore', 'revert'],
    ],
    'header-max-length': [2, 'always', 72],
    'header-trim': [2, 'always'],
    'subject-full-stop': [2, 'never', '.'],
    // A warning: a subject may open with a proper noun, an acronym or a file
    // name such as CLAUDE.md, and this rule cannot tell those from a sentence
    // that was given a capital.
    'subject-case': [
      1,
      'never',
      ['sentence-case', 'start-case', 'pascal-case', 'upper-case'],
    ],

    // --- the scope: optional, and an open list -----------------------------
    // The scopes in use, kept here so that they are in one place. The list is
    // open: this is a warning, so a scope that is not on it is pointed out and
    // the commit goes through. Reuse one before coining another, and add the
    // new one here when you do. No scope at all always passes.
    'scope-enum': [
      1,
      'always',
      [
        // .githooks/ and this file
        'hooks',
        // the docs build: conf.py, the theme, MathJax, the inventories
        'site',
        // pyproject.toml's dependencies and uv.lock
        'deps',
      ],
    ],
    'scope-case': [2, 'always', 'lower-case'],
    'scope-max-length': [2, 'always', 24],

    // --- the body and the footer -------------------------------------------
    'body-leading-blank': [2, 'always'],
    'body-max-line-length': [1, 'always', 72],
    'footer-leading-blank': [1, 'always'],
    // `!` in the header and a `BREAKING CHANGE:` footer: both, or neither.
    'breaking-change-exclamation-mark': [2, 'always'],
  },
};
