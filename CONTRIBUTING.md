# Contributing to Visdom
We want to make contributing to this project as easy and transparent as
possible.

## Pull Requests
We actively welcome your pull requests.

1. Fork the repo and create your branch from `master`.
2. If you've added code that should be tested, add tests.
3. If you've changed APIs, update the documentation.
4. Ensure the Lua and Python interfaces to Visdom are in sync.
5. If you change `js/`, commit the React-compiled version of `main.js`. For details, please see `Contributing to the UI` below.
6. Add demos for new features. Ensure the demos work.
7. Make sure your code lints.
8. If you haven't already, complete the Contributor License Agreement ("CLA").

## Contributing to the UI
The UI is built with [React](https://facebook.github.io/react/). This means that `js/` needs to be compiled. This can be done with `yarn` or `npm`.
To clarify an inconsistency, Panes in the UI are the containers for the
'windows' referred to by the Python and Lua APIs.

#### yarn
You can find instructions for install `yarn` [here](https://yarnpkg.com/lang/en/docs/install/).
```bash
cd /path/to/visdom
yarn             # install node dependencies
yarn run build   # build js
```

#### npm
You can find instructions for installing `npm` [here](https://github.com/npm/npm).
```bash
cd /path/to/visdom
npm install       # install node dependencies
npm run build     # build js
```

## Contributor License Agreement ("CLA")
In order to accept your pull request, we need you to submit a CLA. You only need
to do this once to work on any of Facebook's open source projects.

Complete your CLA here: <https://code.facebook.com/cla>

## Issues
We use GitHub issues to track public bugs. Please ensure your description is
clear and has sufficient instructions to be able to reproduce the issue.

Facebook has a [bounty program](https://www.facebook.com/whitehat/) for the safe
disclosure of security bugs. In those cases, please go through the process
outlined on that page and do not file a public issue.

## Coding Style
* 3 spaces for indentation rather than tabs for Lua
* Follow PEP 8 for Python
* 80 character line length

## License
By contributing to Visdom, you agree that your contributions will be licensed
under the LICENSE file in the root directory of this source tree.
