"""Find/replace widget."""

# FIXME: finding 'as' or 'asa' from 'asasasasa' is broken

import re
import sys
import tkinter
from tkinter import ttk
from typing import Any, Iterator, List, Optional, Tuple, Union, cast
import weakref

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

from porcupine import actions, get_tab_manager, images, tabs


# keys are tabs, values are Finder widgets
finders: 'weakref.WeakKeyDictionary[tabs.FileTab, Finder]' = (
    weakref.WeakKeyDictionary())


class Finder(ttk.Frame):
    """A widget for finding and replacing text.

    Use the pack geometry manager with this widget.
    """

    def __init__(self, parent: tkinter.BaseWidget, textwidget: tkinter.Text, **kwargs: Any) -> None:
        super().__init__(parent, **kwargs)      # type: ignore
        self._textwidget = textwidget

        # grid layout:
        #         column 0        column 1     column 2        column 3
        #     ,---------------------------------------------------------------.
        # row0|     Find:     | text entry    |       | [x] Full words only   |
        #     |---------------|---------------|-------|-----------------------|
        # row1| Replace with: | text entry    |       | [x] Ignore case       |
        #     |---------------------------------------------------------------|
        # row2| button frame, this thing contains a bunch of buttons          |
        #     |---------------------------------------------------------------|
        # row3| status label with useful-ish text                             |
        #     |---------------------------------------------------------------|
        # row4| separator                                                     |
        #     `---------------------------------------------------------------'
        #
        # note that column 2 is used just for spacing, the separator helps
        # distinguish this from e.g. status bar below this
        self.grid_columnconfigure(2, minsize=30)
        self.grid_columnconfigure(3, weight=1)

        # TODO: use the pygments theme somehow?
        textwidget.tag_config(
            'find_highlight', foreground='black', background='yellow')

        self.find_entry = self._add_entry(0, "Find:")
        find_var = self.find_entry['textvariable'] = tkinter.StringVar()
        find_var.trace_add('write', self.highlight_all_matches)

        # because cpython gc
        cast(Any, self.find_entry).lol = find_var

        self.replace_entry = self._add_entry(1, "Replace with:")

        self.find_entry.bind('<Shift-Return>', self._go_to_previous_match)
        self.find_entry.bind('<Return>', self._go_to_next_match)

        # commented out because pressing tab in self.find_entry unselects the
        # text in textwidget for some reason
        #self.replace_entry.bind('<Return>', self._replace_this)

        buttonframe = ttk.Frame(self)
        buttonframe.grid(row=2, column=0, columnspan=4, sticky='we')

        self.previous_button = ttk.Button(buttonframe, text="Previous match",
                                          command=self._go_to_previous_match)
        self.next_button = ttk.Button(buttonframe, text="Next match",
                                      command=self._go_to_next_match)
        self.replace_this_button = ttk.Button(
            buttonframe, text="Replace this match",
            command=self._replace_this)
        self.replace_all_button = ttk.Button(
            buttonframe, text="Replace all",
            command=self._replace_all)

        self.previous_button.pack(side='left')
        self.next_button.pack(side='left')
        self.replace_this_button.pack(side='left')
        self.replace_all_button.pack(side='left')
        self._update_buttons()

        self.full_words_var = tkinter.BooleanVar()
        self.full_words_var.trace_add('write', self.highlight_all_matches)
        self.ignore_case_var = tkinter.BooleanVar()
        self.ignore_case_var.trace_add('write', self.highlight_all_matches)

        # TODO: add keyboard shortcut for "Full words only". I use it all the
        #       time and reaching mouse is annoying. Tabbing through everything
        #       is also annoying.
        ttk.Checkbutton(
            self, text="Full words only", variable=self.full_words_var).grid(
                row=0, column=3, sticky='w')
        ttk.Checkbutton(
            self, text="Ignore case", variable=self.ignore_case_var).grid(
                row=1, column=3, sticky='w')

        self.statuslabel = ttk.Label(self)
        self.statuslabel.grid(row=3, column=0, columnspan=4, sticky='we')

        ttk.Separator(self, orient='horizontal').grid(
            row=4, column=0, columnspan=4, sticky='we')

        closebutton = ttk.Label(self, cursor='hand2')
        closebutton.place(relx=1, rely=0, anchor='ne')
        closebutton.bind('<Button-1>', self.hide)

        # TODO: figure out why images don't work in tests
        if 'pytest' not in sys.modules:     # pragma: no cover
            closebutton['image'] = images.get('closebutton')

        # explained in test_find_plugin.py
        textwidget.bind('<<Selection>>', self._update_buttons, add=True)

    def _add_entry(self, row: int, text: str) -> ttk.Entry:
        ttk.Label(self, text=text).grid(row=row, column=0, sticky='w')
        entry = ttk.Entry(self, width=35, font='TkFixedFont')
        entry.bind('<Escape>', self.hide)
        entry.grid(row=row, column=1, sticky='we')
        return entry

    def show(self) -> None:
        self.pack(fill='x')
        self.find_entry.focus_set()
        self.highlight_all_matches()

    def hide(self, junk: object = None) -> None:
        # remove previous highlights from highlight_all_matches
        self._textwidget.tag_remove('find_highlight', '1.0', 'end')

        self.pack_forget()
        self._textwidget.focus_set()

    # tag_ranges returns (start1, end1, start2, end2, ...), and this thing
    # gives a list of (start, end) pairs
    def get_match_ranges(self) -> List[Tuple[str, str]]:
        starts_and_ends = list(
            map(str, self._textwidget.tag_ranges('find_highlight')))
        assert len(starts_and_ends) % 2 == 0
        pairs = list(zip(starts_and_ends[0::2], starts_and_ends[1::2]))
        return pairs

    # must be called when going to another match or replacing becomes possible
    # or impossible, i.e. when find_highlight areas or the selection changes
    def _update_buttons(self, junk: object = None) -> None:
        # TODO: document this trick
        State = Union[Literal['normal'], Literal['disabled']]
        matches_something_state: State
        replace_this_state: State

        matches_something_state = (
            'normal' if self.get_match_ranges() else 'disabled')

        try:
            start, end = map(str, self._textwidget.tag_ranges('sel'))
        except ValueError:
            replace_this_state = 'disabled'
        else:   # no, elif doesn't work here
            if (start, end) in self.get_match_ranges():
                replace_this_state = 'normal'
            else:
                replace_this_state = 'disabled'

        self.previous_button['state'] = matches_something_state
        self.next_button['state'] = matches_something_state
        self.replace_this_button['state'] = replace_this_state
        self.replace_all_button['state'] = matches_something_state

    def _get_matches_to_highlight(self, looking4: str) -> Iterator[str]:
        nocase_opt = self.ignore_case_var.get()
        if self.full_words_var.get():
            # tk doesn't have python-style \b, but it has \m and \M that match
            # the beginning and end of word, see re_syntax(3tcl)
            #
            # TODO: are there \w characters that need to be escaped? this is
            # validated in highlight_all_matches()
            search_arg = r'\m' + looking4 + r'\M'
            regexp_opt = True
        else:
            search_arg = looking4
            regexp_opt = False

        start_index = '1.0'
        first_time = True

        while True:
            # searching at the beginning of a match gives that match, not
            # the next match, so we need + 1 char... unless we are looking
            # at the beginning of the file, and to avoid infinite
            # recursion, we check for that by checking if we have done it
            # before
            if first_time:
                start_index_for_search = start_index
                first_time = False
            else:
                start_index_for_search = '%s + 1 char' % start_index

            start_index = self._textwidget.search(
                search_arg, start_index_for_search, 'end',
                nocase=nocase_opt, regexp=regexp_opt)
            if not start_index:
                # no more matches
                break
            yield start_index

    def highlight_all_matches(self, *junk: object) -> None:
        # clear previous highlights
        self._textwidget.tag_remove('find_highlight', '1.0', 'end')

        looking4 = self.find_entry.get()
        if not looking4:    # don't search for empty string
            self._update_buttons()
            self.statuslabel['text'] = "Type something to find."
            return
        if self.full_words_var.get():
            # check for non-wordy characters
            match = re.search(r'\W', looking4)
            if match is not None:
                self._update_buttons()
                self.statuslabel['text'] = ('The search string can\'t contain '
                                            '"%s" when "Full words only" is '
                                            'checked.' % match.group(0))
                return

        count = 0
        for start_index in self._get_matches_to_highlight(looking4):
            self._textwidget.tag_add(
                'find_highlight', start_index,
                '%s + %d chars' % (start_index, len(looking4)))
            count += 1

        self._update_buttons()
        if count == 0:
            self.statuslabel['text'] = "Found no matches :("
        elif count == 1:
            self.statuslabel['text'] = "Found 1 match."
        else:
            self.statuslabel['text'] = "Found %d matches." % count

    def _select_range(self, start: str, end: str) -> None:
        # the tag_lower makes sure sel shows up, hiding find_highlight under it
        self._textwidget.tag_lower('find_highlight', 'sel')
        self._textwidget.tag_remove('sel', '1.0', 'end')
        self._textwidget.tag_add('sel', start, end)
        self._textwidget.mark_set('insert', start)
        self._textwidget.see(start)

    # TODO: adjust scrolling accordingly
    def _go_to_next_match(self, junk: object = None) -> None:
        pairs = self.get_match_ranges()
        if not pairs:
            # the "Next match" button is disabled in this case, but the key
            # binding of the find entry is not
            self.statuslabel['text'] = "No matches found!"
            return

        # find first pair that starts after the cursor
        for start, end in pairs:
            if self._textwidget.compare(start, '>', 'insert'):
                self._select_range(start, end)
                break
        else:
            # reached end of file, use the first match
            self._select_range(*pairs[0])

        self.statuslabel['text'] = ""
        self._update_buttons()

    # see _go_to_next_match for comments
    def _go_to_previous_match(self, junk: object = None) -> None:
        pairs = self.get_match_ranges()
        if not pairs:
            self.statuslabel['text'] = "No matches found!"
            return

        for start, end in reversed(pairs):
            if self._textwidget.compare(start, '<', 'insert'):
                self._select_range(start, end)
                break
        else:
            self._select_range(*pairs[-1])

        self.statuslabel['text'] = ""
        self._update_buttons()
        return

    def _replace_this(self, junk: object = None) -> None:
        if str(self.replace_this_button['state']) == 'disabled':
            self.statuslabel['text'] = (
                'Click "Previous match" or "Next match" first.')
            return

        # highlighted areas must not be moved after .replace, think about what
        # happens when you replace 'asd' with 'asd'
        start, end = self._textwidget.tag_ranges('sel')
        self._textwidget.tag_remove('find_highlight', start, end)
        self._update_buttons()
        self._textwidget.replace(start, end, self.replace_entry.get())

        self._textwidget.mark_set('insert', start)
        self._go_to_next_match()

        left = len(self.get_match_ranges())
        if left == 0:
            self.statuslabel['text'] = "Replaced the last match."
        elif left == 1:
            self.statuslabel['text'] = (
                "Replaced a match. There is 1 more match.")
        else:
            self.statuslabel['text'] = (
                "Replaced a match. There are %d more matches." % left)

    def _replace_all(self) -> None:
        match_ranges = self.get_match_ranges()

        # must do this backwards because replacing may screw up indexes AFTER
        # the replaced place
        for start, end in reversed(match_ranges):
            self._textwidget.replace(start, end, self.replace_entry.get())
        self._textwidget.tag_remove('find_highlight', '1.0', 'end')
        self._update_buttons()

        if len(match_ranges) == 1:
            self.statuslabel['text'] = "Replaced 1 match."
        else:
            self.statuslabel['text'] = ("Replaced %d matches." %
                                        len(match_ranges))


def find() -> None:
    tab = get_tab_manager().select()
    assert isinstance(tab, tabs.FileTab)
    if tab not in finders:
        finders[tab] = Finder(tab.bottom_frame, tab.textwidget)
    finders[tab].show()


def setup() -> None:
    actions.add_command("Edit/Find and Replace", find, '<Control-f>',
                        tabtypes=[tabs.FileTab])
