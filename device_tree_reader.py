# reference: https://github.com/devicetree-org/devicetree-specification/releases ; v0.3
# TODO-low ADD UNIT TEST EVERYWHERE! :D (sim? não?)
from pathlib import Path
from enum import Enum, auto

import re
import pprint

# from treelib import Tree, Node
from anytree import Node, RenderTree, NodeMixin, PreOrderIter

from typing import Union, List, Iterator, AnyStr, Optional

from find_in_devicetree.find_in_dt import find_in_dt

DEBUG = False


class Token:
    end = r';'

    # only outside of every node
    include_macro = r'#include'
    include_same_dir = r'"'
    start_include_default_dir = r'<'
    end_include_default_dir = r'>'

    dts_extention = r'dts'
    dtsi_extention = r'dtsi'
    header_extention = r'h'

    dts_version = r'/dts-v1/'
    overlay = r'/plugin/'

    root_node = r'/'

    start_node = r'{'
    end_node = r'}'

    at = r'@'

    start_array = r'<'
    end_array = r'>'

    string = r'"'

    assignment = r'='

    simple_comment = r'//'
    start_comment = r'*/'
    end_comment = r'/*'

    phandle_pointer = r'&'

    phandle = r':'

    size_definition = r'#'


class State(Enum):
    Comment = auto()  # inside a comment (multiline or not)
    Node = auto()  # inside a node
    RootNode = auto()  # directly inside THE root node (maybe not useful?)
    IncludeLine = auto()  # inside a include line
    IncludeFileName = auto()  # inside a included file name (that should be inside a include line and could be surrounded by "double quotes" or <angle brackets>)
    String = auto()  # inside a string ( "string" )
    PropertyLine = auto()  # inside a property line (something = anything)
    Array = auto()  # inside an array ( <one two three ... > )


class Regex:
    include_same_dir = r'#include +"(?P<file_path>[^"]+?)"'  # group 0: path and file name with extension
    include_default_dir = r'#include +<(?P<file_path>[^>]+?)>'  # group 0: path and file name with extension

    valid_node_name = r'[\w,\.\+-]+'
    valid_property_name = r'[\w,\.\+\?#-]+'

    boring = r'^\s*$'

    root_node = r'/ {'

    node = f'(?P<name>{valid_node_name})(?:@(?P<value>{valid_node_name})) +{{'

    multiline_comment = r'/\*(?:[^/*][^*]*\*+)*/'
    '''inspired by https://stackoverflow.com/a/36328890/6609908'''


class Phandle:
    '''
    &gpio2 -> node (""pointer"" to a node)
    This guy is NOT responsible for dealing with files!
    '''
    re_phandle = re.compile(r'^(?P<name>&[\w,.+\-]+)$')

    def __init__(self, name:str):
        phandle_name = Phandle.check_name(name)
        if not phandle_name:
            raise ValueError(f'{name} is NOT a valid phandle_name name!')

        self._name = phandle_name

        # self._original_file:Union[None, Path] = None
        # self._referenced_in_files:List[Path] = []
    #
    # @property
    # def referenced_in_files(self) -> List[Path]:
    #     return self._referenced_in_files
    #
    # @property
    # def original_file(self) -> Path:
    #     return self._original_file
    #
    # def referenced_in(self, file:Path) -> None:
    #     self._referenced_in_files.append(file)
    #
    # def original_file_is(self, file:Path) -> None:
    #     self._original_file = file

    @property
    def name(self):
        return self._name

    @classmethod
    def check_name(cls, string:str):
        phandle = cls.re_phandle.match(string)
        if phandle:
            return phandle['name']
        else:
            return None

    @classmethod
    def from_string(cls, string:str):
        phandle = cls.check_name(string)
        if phandle:
            return cls(phandle)
        else:
            return None

    def __str__(self):
        return self._name

    def __repr__(self):
        return f'<Phandle>{self._name}'

class IfBlock:
    def __init__(self):
        self.line_span = []
        self._directives = {}

class CMacro:
    '''
    PINGPIO2_GPIO1_IO15 (a c-style macro - probably defined in a header)
    '''
    re_macro = re.compile(r'^(?P<name>[a-zA-Z_][a-zA-Z0-9_]+)$')

    def __init__(self, name:str):
        macro = CMacro.check_name(name)
        if not macro:
            raise ValueError(f'{name} is NOT a valid c-style macro name!')

        self._name = macro

    @property
    def name(self):
        return self._name

    @classmethod
    def check_name(cls, string:str):
        macro = cls.re_macro.match(string)
        if macro:
            return macro['name']
        else:
            return None

    @classmethod
    def from_string(cls, string:str):
        macro = cls.check_name(string)
        if macro:
            return cls(macro)
        else:
            return None

    def __str__(self):
        return self._name

    def __repr__(self):
        return f'<CMacro>{self._name}'


class BinaryExpression:

    def __init__(self, original_string:str, cmacros_list:Optional[List[CMacro]] = None):
        self._cmacros = cmacros_list
        self._original_string = original_string

    @classmethod
    def from_string(cls, string:str):
        if string[0] == '(' and string[-1] == ')':
            cmacros_found = re.finditer(r'[A-Z_][A-Z0-9_]+', string)
            cmacros_list = []
            for cmacro_hit in cmacros_found:
                # TODO should I store the position of the CMacros? How? Here we don't have access to the "big-picture"
                cmacros_list.append(CMacro.from_string(cmacro_hit[0]))

            return cls(string, cmacros_list)
        else:
            raise ValueError(f'Are you sure that this {string} is a {cls.__name__}?')



def some_expression(string:str, start: str = '(', end: str = ')'):
    if start in string:
        start_index = string.index(start)
        counter = 0
        for idx in range(start_index, len(string)):
            if string[idx] == start:
                counter+=1
            if string[idx] == end:
                counter-=1
            if counter == 0:
                break
        end_index = idx+1
    return string[start_index:end_index]

class MixinIteratorProperty(Iterator):

    def __iter__(self):
        self.iter = iter(self._value)
        return self

    def __next__(self):
        return next(self.iter)


class StringProperty:
    '''string-property = "a string";'''
    re_string = re.compile(r'^"(?P<string>[^\n;"]*)"$')

    def __init__(self, value: str):
        self._value: str = value

    def __str__(self):
        return self._value

    def __repr__(self):
        return f'<StringProperty>{self._value}'

    @classmethod
    def from_string(cls, string: str):
        string_property = cls.re_string.match(string)
        if string_property:
            return cls(string_property['string'])
        else:
            return None


class StringListProperty(MixinIteratorProperty):
    '''string-list = "red fish", "blue fish";'''
    re_string_list = re.compile(r'^("[^\n;"]*"\s*,\s*?)+"[^\n;"]*"$')
    re_string_single = re.compile(r'"([^\n;"]*)"')

    def __init__(self, value: List[str]):
        self._value: List[str] = value

    def __repr__(self):
        return f'<StringListProperty>{repr(self._value)}'

    def __str__(self):
        return repr(self._value)

    def __getitem__(self, key: int):
        return self._value[key]

    def __setitem__(self, key: int, value: List[str]):
        self._value[key] = value

    @classmethod
    def from_string(cls, string: str):
        string_list_property = cls.re_string_list.match(string)
        if string_list_property:
            strings = cls.re_string_single.findall(string)
            return cls(strings)
        else:
            return None

class Integer:
    def __init__(self, integer_number:int, original:str='hex'):
        if not original in ['hex', 'dec', 'bin']:
            raise ValueError(f'Argument "original" should be "dec", "hex", or "bin". Got "{original}" instead!')

        self._value = integer_number
        self._original_base = original

        self._hex_str =  f'0x{self._value:X}'
        self._dec_str =  f'{self._value}'
        self._bin_str =  f'0b{self._value:b}'

        if self._original_base == 'hex':
            self._original_string = self._hex_str
        elif self._original_base == 'dec':
            self._original_string = self._dec_str
        else: # original string was in binary (2 base)
            self._original_string = self._bin_str

    @property
    def original_string(self):
        return self._original_string

    @property
    def hex_str(self):
        return self._hex_str

    @property
    def dec_str(self):
        return self._dec_str

    @property
    def bin_str(self):
        return self._bin_str

    def __repr__(self):
        return self._original_string

    @classmethod
    def from_string(cls, string:str):
        integer = 0
        if string[0:2] == '0x' or string[0:2] == '0X':
            try:
                integer = int(string, 16)
                return cls(integer, original='hex')
            except:
                raise ValueError(f'Why is not {string} an hexadecimal value?')

        if string[0:2] == '0b' or string[0:2] == '0B':
            try:
                integer = int(string, 2)
                return cls(integer, original='bin')
            except:
                raise ValueError(f'Why is not {string} a binary value?')

        try:
            integer = int(string, 10)
            return cls(integer, original='dec')
        except:
            raise ValueError(f'Why is not {string} a decimal value?')

class CellProperty(MixinIteratorProperty):
    '''cell-property = <0xbeef 123 0xabcd1234>;'''
    re_cell = re.compile(r'^<([^>]+)>\s*$')
    re_binary_operation = re.compile(r'\(\s*[A-Z0-9_]+\s*([|&]\s*[A-Z0-9_]+\s*)\)')
    re_binary_expression = re.compile(r'\(')

    def __init__(self, value: List[Union[int, Phandle, CMacro, BinaryExpression]]):
        self._value: List[Union[int, Phandle, CMacro, BinaryExpression]] = value

    def __repr__(self):
        return f'<CellProperty>{repr(self._value)}'

    def __str__(self):
        return repr(self._value)

    def __getitem__(self, key: int):
        return self._value[key]

    def __setitem__(self, key: int, value: List[Union[int, Phandle, CMacro, BinaryExpression]]):
        self._value[key] = value

    @classmethod
    def from_string(cls, string: str):
        string = re.sub(Regex.multiline_comment, '', string)
        binary_operation = cls.re_binary_expression.search(string)
        place_holders = {}
        substitutions_amount = 0
        while binary_operation:
            substitutions_amount += 1
            count = 1
            past_one_char = binary_operation.start()+1
            while not count == 0:
                if string[past_one_char] == ')':
                    count -= 1
                elif string[past_one_char] == '(':
                    count += 1
                past_one_char += 1
            place_holders[f'{{{{{substitutions_amount}}}}}'] = string[binary_operation.start():past_one_char]
            string = re.sub(re.escape(string[binary_operation.start():past_one_char]), f'{{{{{substitutions_amount}}}}}', string)
            binary_operation = cls.re_binary_expression.search(string)

        cell = cls.re_cell.match(string)
        if cell:
            elements = cell[1].split()
            for i in range(len(elements)):  # I want to edit elements in place
                try:
                    elements[i] = Integer.from_string(elements[i])
                except ValueError:
                    for element_class in [Phandle, CMacro]:
                        try_class = element_class.from_string(elements[i])
                        if try_class:
                            elements[i] = try_class
                            break
                    else:
                        if re.match(r'{{\d+}}', elements[i]):
                            elements[i] = BinaryExpression.from_string(place_holders[elements[i]])
                        else:
                            raise ValueError(f'Why is not {elements[i]} a hexadecimal, decimal, phandle nor a c-style macro?! WHAT IS IT?!')

            return cls(elements)
        else:
            return None


class BinaryProperty(MixinIteratorProperty):
    '''binary-property = [0x01 0x23 0x45 0x67];'''
    re_binary = re.compile(r'^\[([^\]]+)\]\s*$')

    def __init__(self, value: List[int]):
        self._value: List[int] = value

    def __repr__(self):
        return f'<BinaryProperty>{repr(self._value)}'

    def __str__(self):
        return repr(self._value)

    def __getitem__(self, key: int):
        return self._value[key]

    def __setitem__(self, key: int, value: List[int]):
        self._value[key] = value

    @classmethod
    def from_string(cls, string: str):
        cell = cls.re_binary.match(string)
        if cell:
            elements = cell[1].split()
            for i in range(len(elements)):  # I want to edit elements in place
                if elements[i][0:2] == '0x' or elements[i][0:2] == '0X':
                    try:
                        elements[i] = int(elements[i], 16)
                    except:
                        raise ValueError(f'Why is not {elements[i]} an hexa value?')
                else:
                    try:
                        elements[i] = int(elements[i], 10)
                    except:
                        raise ValueError(f'Why is not {elements[i]} a decimal value?')

            return cls(elements)
        else:
            return None


class EmptyProperty:
    '''wakeup-source;'''

    def __init__(self):
        self._status = True

    def __bool__(self):
        return self._status

    def __repr__(self):
        return f'<EmptyProperty>{self._status}'

    def __str__(self):
        return self._status


class MixedProperty(MixinIteratorProperty):
    '''mixed-property = "a string", [0x01 0x23 0x45 0x67], <0x12345678>;'''
    re_mixed_property = re.compile(
        r'(?:(?P<cell><\s*(?:(?:\s*&)?\w+\s*)+>)|(?P<string>"(?:[^\n;"]*)"\s*)|(?P<binary>\[\s*(?:(?:(?:0[xX][\dA-Fa-f]+)|(?:\d+))\s*)+\]))')

    def __init__(self, value: List[Union[StringProperty,
                                         CellProperty,
                                         BinaryProperty]] = []):
        self._value = value

    def __repr__(self):
        return f'<MixedProperty>[{", ".join([repr(v) for v in self._value])}]'

    def __str__(self):
        return repr(self._value)

    def get_type_info(self):
        type_list = [type(element) for element in self]
        return type_list

    def append(self, value: Union[StringProperty,
                                  CellProperty,
                                  BinaryProperty]) -> None:
        self._value.append(value)

    @classmethod
    def from_string(cls, string: str):
        mixed_property = cls.re_mixed_property.finditer(string)
        if mixed_property:
            auxMixedProperty: MixedProperty = MixedProperty()
            for p in mixed_property:
                # TODO there is a OR for the groups... do i need to evaluate if more than one was found?
                if not sum([0 if v == None else 1 for v in p.groupdict().values()]) == 1:
                    raise ValueError(
                        f'More than one type (string and/or cell and/or binary) found: {[f"{k}: {v}" for k, v in p.groupdict().items() if not v == None]}')
                elif not p['cell'] == None:
                    current_property = CellProperty.from_string(p['cell'])
                elif not p['string'] == None:
                    current_property = StringProperty.from_string(p['string'])
                elif not p['binary'] == None:
                    current_property = BinaryProperty.from_string(p['binary'])
                else:
                    raise f'Something is wrong! None of cell, string or binary. What is this?? value: {p[0]}'

                auxMixedProperty.append(current_property)

            return auxMixedProperty
        else:
            return None


class AliasProperty(Phandle):
    '''&phandle;'''
    pass


NodePropertyValue = Union[StringProperty,
                          CellProperty,
                          StringListProperty,
                          BinaryProperty,
                          MixedProperty,
                          EmptyProperty,
                          AliasProperty]


class ValueElement:
    def __init__(self, value: NodePropertyValue, file_path: Path, line_number: List[int], key_span: List[int],
                 value_span: List[int]):
        self.value: NodePropertyValue = value
        self.file_path: Path = file_path
        self.line_number: List[int] = line_number
        self.single_line: bool = len(line_number) == 1
        self.key_span: List[int] = key_span
        self.value_span: List[int] = value_span


class DeviceTreeNodeProperty:

    def __init__(self, name: str, value: NodePropertyValue, file_path: Path, line_number: List[int],
                 key_span: List[int], value_span: List[int]):
        self._name: str = name
        self._value: NodePropertyValue = value
        self._history_list: List = [ValueElement(self._value, file_path, line_number, key_span, value_span)]

    @property
    def name(self):
        return self._name

    @property
    def value(self):
        return self._value

    def set_value(self, value: NodePropertyValue, file_path: Path, line_number: List[int], key_span: List[int],
                  value_span: List[int]):
        if isinstance(value, self.type):
            self._value = self._value
            self._history_list.append(ValueElement(self._value, file_path, line_number, key_span, value_span))
        else:
            raise TypeError(
                f'The property {self._name} was created as {self.type}, but the new value {value} is of type {type(value)}!')

    @property
    def type(self):
        return type(self._value)

    @property
    def history_list(self):
        return self._history_list

    def __repr__(self):
        return f'{self.name} : {repr(self._value)}'


class DeviceTreeNode(NodeMixin):

    # TODO-low: remove the default file_path_source
    def __init__(self, name: str, is_overlay: bool = False, file_path_source: Path = Path(), phandle: str = None,
                 at: Union[str, int] = None, parent=None, children=None):
        """

        @param name: name of the node in this this case: "phandle: name@reg" ; or in this case: "&name"
        @type name: str
        @param is_overlay: for the "&name" case, is_overlay must be true
        @type is_overlay: bool
        @param file_path_source: the source file responsible for this "instance" of this node
        @type file_path_source: Path
        @param phandle: the phandle for this node
        @type phandle: str
        @param at: the reg for this node
        @type at: int
        @param parent: this node's parent node. for the root node (/), the parent is None
        @type parent: dunno
        @param children: children node of this node
        @type children: dunno
        """
        if is_overlay and (phandle or at):
            raise ValueError(
                'An overlay can not have a phandle nor an at (@) value! (or can it?)\nFor an overlay node, the "&node_name" is its name! ')
        else:
            self._at = at
            self._phandle = phandle

        super(DeviceTreeNode, self).__init__()
        self._properties: dict = {}

        self.name: str = name
        self._is_overlay = is_overlay
        self._file_path_source = file_path_source
        self._properties_span = [-1, -1]
        self._node_span = [-1, -1]

        self.parent = parent
        self.children = [] if children == None else children

    def add_property(self, name: str, value: NodePropertyValue, file_source: Path,
                     line_number: List[int], key_span: List[int], value_span: List[int]) -> None:
        """

        @param name: the name of the property
        @type name: str
        @param value: the value of the property
        @type value: NodePropertyValue
        @param file_source: the source file responsible for this property's value
        @type file_source: Path
        @param line_number: the first [and maybe last] line in the source file that this property and its value are
        @type line_number: List[int]
        @param key_span: position of the key's first char in this source file and also the one past key's last char
        @type key_span: List[int]
        @param value_span: position of the value's first char in this source file and also the one past value's last char
        @type value_span: List[int]
        @return: Nothing. It just adds (creates) the property
        @rtype: None
        """

        if name in self._properties:
            raise KeyError(f'Property {name} already exist!')
        else:
            self._properties[name] = DeviceTreeNodeProperty(name, value, file_source, line_number, key_span, value_span)

    def modify_property(self, name: str, value: Union[str, None]) -> None:
        if not name in self._properties:
            raise KeyError(f'Property {name} can not be modified because it does not exist yet!')
        else:
            self._properties[name] = value

    def remove_property(self, name: str) -> None:
        if self._properties.get(name) == None:
            raise KeyError(f'Property {name} can not be modified because it does not exist!')
        else:
            self._properties.pop(name)

    # def set_phandle(self, phandle:str) -> None:
    #     if not self._phandle == None:
    #         raise ValueError(f'Node already has a phandle {self._phandle} !')
    #     else:
    #         self._phandle = phandle

    @property
    def phandle(self) -> str:
        '''
        returns phandle string for this node
        @return: phandle string for this node
        @rtype: str
        '''
        return self._phandle

    def set_at(self, at: Union[str, int]) -> None:
        if not self._at == None:
            raise ValueError(f'Node already has an @ {self._at} !')
        else:
            self._at = at

    def get_at(self) -> Union[str, int]:
        return self._at

    def set_properties_span_start(self, span_start: int):
        self._properties_span[0] = span_start

    def set_properties_span_end(self, span_end: int):
        self._properties_span[1] = span_end

    def get_properties_span(self):
        return self._properties_span

    def set_node_span_start(self, span_start: int):
        self._node_span[0] = span_start

    def set_node_span_end(self, span_end: int):
        self._node_span[1] = span_end

    def get_node_span(self):
        return self._node_span

    # TODO-low add __getitem__ to expose properties by its names
    # TODO-low add property_names to expoose all property names

    def __repr__(self):
        string = self.name
        if not self._at == None:
            string = f'{string} @ {self._at}'
        if not self._phandle == None:
            string = f'{self._phandle} : {string}'
        if self._is_overlay:
            string = f'{string} - overlay'

        string = f'{string}\n\t<{self._properties_span[0]}, {self._properties_span[1]}>'
        properties_part = '\n\t'.join([f'{v}' for v in self._properties.values()])
        string = f'{string}\n\t{properties_part}'

        return string

    def __getitem__(self, node_name_or_phandle):
        for node in self.children:
            if node.name == node_name_or_phandle or node.phandle == node_name_or_phandle:
                return node
        else:
            raise ValueError(f'Não encontrei {node_name_or_phandle} dentro de {self.name}')

    def find_node(self, node_name_or_phandle):
        hits = []
        for node in PreOrderIter(self):
            if node.name == node_name_or_phandle or node.phandle == node_name_or_phandle:
                hits.append(node)

class SourceFileType(Enum):
    HEADER = auto()
    DTSI = auto()
    DTS = auto()

class SourceFile:

    def __init__(self, file_path:Union[str, Path]):
        if isinstance(file_path, str):
            file_path = Path(file_path)
        if not file_path.is_file():
            raise ValueError(f'file_path should be and file! Got {file_path} instead!')
        self._path = file_path
        if self._path.suffix == '.h':
            self._type:SourceFileType = SourceFileType.HEADER
        if self._path.suffix == '.dtsi':
            self._type:SourceFileType = SourceFileType.DTSI
        if self._path.suffix == '.dts':
            self._type:SourceFileType = SourceFileType.DTS

    @property
    def type(self):
        return self._type

class WholeDeviceTree():
    def __init__(self, nodes: Optional[List[DeviceTreeNode]]=None):
        self._root_node = DeviceTreeNode('/')
        '''the one and only root node'''
        self._phandles:dict = {}
        '''dictionary from phandle string to node'''
        self._nodes:dict = {}
        '''
        dictionary from node name to node.
        not useful to track and apply node modification (it is always don through phandles!)
        '''
        if nodes:
            for node in nodes:
                if not node.name in self._nodes:
                    self._nodes[node.name] = node
                if node.phandle and not node.phandle in self._phandles:
                    self._phandles[node.phandle] = node

        self._source_file_list = []
        # TODO could the dependency be a directional graph? (networkx)
        self._source_file_dependency = []

    def register_phandle(self, phandle, node: DeviceTreeNode):
        self._phandles[phandle] = node

    def register_all_from_node(self, node: DeviceTreeNode):
        n: DeviceTreeNode
        for n in PreOrderIter(node):
            if not n.name in self._nodes[n.name]:
                self._nodes[n.name] = n
                if not n.phandle in self._phandles:
                    if n.phandle:
                        self._phandles[n.phandle] = n

    def register_all_from_root(self, any_node: DeviceTreeNode):
        if not any_node.parent == None:
            any_node = any_node.parent
        self.register_all_from_node(any_node)


def get_line_number(text_contents):
    if len(text_contents) == 0:
        return 0
    else:
        return 1 + text_contents.count('\n')


def parse_device_tree(file_path: Path) -> None:
    global DEBUG
    if not file_path.exists():
        raise FileExistsError(f"{file_path} does not exist!")

    if not file_path.is_file():
        raise FileExistsError(f"{file_path} is not a file!")

    with open(file_path, 'r') as f:
        contents = f.read()

    root_node: re.Match = re.search(Regex.root_node, contents)

    if root_node == None:
        raise ValueError(f'Root node ( / ) could not be found in {file_path}!')

    # visualization
    # https://regexper.com/#%28%3F%3A%28%3F%3A%28%26%28%5B%5Cw%2C.%2B%5C-%2F%5D%2B%29%29%7C%28%28%3F%3A%28%5B%5Cw%2C.%2B%5C-%2F%5D%2B%29%20*%3A%20*%29%3F%28%5B%5Cw%2C.%2B%5C-%2F%5D%2B%29%28%3F%3A%40%28%5B%5Cw%2C.%2B%5C-%5D%2B%29%29%3F%29%29%20*%7B%29%7C%28%20*%7D%3B%29
    # device tree specification v0.3 (13/feb/2020): https://github.com/devicetree-org/devicetree-specification/releases/tag/v0.3
    # labels (phandles) : section 6.2 : [\w]+
    # node name : section 2.2.1 : [\w,.\+\-]+
    # unit-address : section 2.2.1 (same as nome name) : [\w,.\+\-]+
    node_scopes = re.finditer(
        r'((?:(&(?P<phandle_only>[\w,.+\-]+))|((?:(?P<phandle>[\w,.+\-]+) *: *)?(?P<name>[\w,.+\-/]+)(?:@(?P<at>[\w,.+\-]+))?)) *{)|( *};)',
        contents)

    c = 0
    '''double of the amount of nodes'''

    node_count = 0
    '''the amount of nodes'''

    current_node = None
    '''current node being evaluated'''

    root_nodes = []
    '''every node that is not inside of another node in the current file
    (in other words: the root node ("/") and every "overlay" node in the current file)'''

    # for DEBUG
    pre = ''
    t = 0
    # for DEBUG

    math: re.Match
    '''for iteration over regexp matches in this file'''
    for match in node_scopes:
        if match[0][-1] == '{':
            '''here we have the start of a node'''
            node_count += 1

            # this is needed because of the pop below
            node_header = match.groupdict()
            if node_header['phandle_only'] == None:
                '''this is not an overlay node'''
                node_header.pop('phandle_only')
                if node_header['name'] == '/':
                    '''this is the root node'''
                    current_node = DeviceTreeNode(**node_header)
                    root_nodes.append(current_node)
                else:
                    '''not the root node and not an overlay node'''
                    if current_node.get_properties_span()[1] == -1:
                        '''if we found a new node, the property section of the previous node has to end'''
                        current_node.set_properties_span_end(match.span()[0])
                    new_node = DeviceTreeNode(**node_header, parent=current_node)
                    current_node = new_node

                '''grabbing the start of the node property (it is the first character that indicates a property)'''
                carret_position = match.span()[1]
                # while contents[carret_position] == ' ' or contents[carret_position] == '\t' or contents[carret_position] == '\n':
                #    carret_position += 1
                #    if carret_position > len(contents):
                #        raise ValueError(f'Reached End Of File {file_path}!')
                print('AE CARAI', current_node.name)
                current_node.set_properties_span_start(carret_position)
                if DEBUG:
                    if contents[current_node.get_properties_span()[0]] == '\n':
                        print(f'{current_node.name} : first property char is linefeed {node_count}')
                    else:
                        print(
                            f'{current_node.name} : first property char is NOT linefeed: {contents[current_node.get_properties_span()[0]]} {node_count}')
                current_node.set_node_span_start(match.span()[1])

                if DEBUG:
                    print(f'{pre}{current_node.name} start')
                    t += 1
                    pre = '.' * t
            else:
                '''here we have an overlay node'''
                if not current_node == None:
                    '''an overlay node can not not be inside any other node (or can it?)'''
                    raise KeyError(
                        f'This {match[0]} node is only a phandle. Should this be inside a node ({current_node.name})? Is this allowable?')
                else:
                    '''the overlay node is not inside another node'''
                    current_node = DeviceTreeNode(name=node_header['phandle_only'], is_overlay=True)
                    root_nodes.append(current_node)
                    current_node.set_node_span_start(match.span()[1])
                    carret_position = match.span()[1]
                    # while contents[carret_position] == ' ' or contents[carret_position] == '\t' or contents[carret_position] == '\n':
                    #     carret_position += 1
                    #     if carret_position > len(contents):
                    #         raise ValueError(f'Reached End Of File {file_path}!')
                    current_node.set_properties_span_start(carret_position)
                    if DEBUG:
                        if contents[current_node.get_properties_span()[0]] == '\n':
                            print(f'{current_node.name} : first property char is linefeed {node_count}')
                        else:
                            print(
                                f'{current_node.name} : first property char is NOT linefeed: {contents[current_node.get_properties_span()[0]]} {node_count}')

                    if DEBUG:
                        print(f'{pre}{current_node.name} start')
                        t += 1
                        pre = '.' * t


        elif match[0] == '};' and match['name'] == None:
            if DEBUG:
                t -= 1
                pre = '.' * t
                print(f'{pre}{current_node.name} end')
            if current_node.get_properties_span()[1] == -1:
                current_node.set_properties_span_end(match.span()[0])
            current_node.set_node_span_end(match.span()[0])
            current_node = current_node.parent
        else:
            raise ValueError('deu ruim')
        c += 1

    if DEBUG:
        print(list(PreOrderIter(root_nodes[0])))

    if DEBUG:
        for rn in root_nodes:
            for node in PreOrderIter(rn):
                print(node, type(node))
                print(node.get_properties_span())
                print('/**/', contents[node.get_properties_span()[0]:node.get_properties_span()[1]], '/**/')

    if DEBUG:
        for rn in root_nodes:
            print(RenderTree(rn))

    '''
    at this point we have al spans for each node and its properties
    time to parse it all
    '''

    print('\n\nproperties time\n\n')

    for root in root_nodes:
        '''tree by tree'''
        node: DeviceTreeNode
        for node in PreOrderIter(root):
            '''node by node'''
            if DEBUG:
                print(f'==|{node.name}|==')

            properties_lines = contents[node.get_properties_span()[0]:node.get_properties_span()[
                1]]  # getting online the properties

            carret_position = node.get_properties_span()[0]
            '''curernt carret position in our analysis'''

            line_number_offset = get_line_number(contents[:carret_position - 1])
            '''curernt line number in our analysis'''

            if DEBUG:
                w = 20
                print(f'{line_number_offset:{w - 10}} {node.name:{w}} {properties_lines[:10]:{w}}')

            '''dealing with #if... , #el..., #endif '''

            begin_control_block = re.search(r'\n\s*#(?P<directive>if(?:def)?|else|elif)\s*(?P<expression>[^\n]+)?\n', properties_lines)
            if begin_control_block:
                line_begin_control_block = get_line_number(contents[:carret_position - 1])
                begin_control_block = re.search(r'\n\s*#(?P<directive>if(?:def)?|else|elif)\s*(?P<expression>[^\n]+)?\n', properties_lines,)

            # device tree specification v0.3 (13/feb/2020): https://github.com/devicetree-org/devicetree-specification/releases/tag/v0.3
            # property names : section 2.2.4 : [\w,.+?#\-]+

            key_value_property: Iterator[re.Match[AnyStr]] = re.finditer(
                r'(?P<key>[\w,.+?#\-]+)\s*=\s*(?P<value>[^;]+);', properties_lines)
            '''this a property like <key = value>, regardless of being spread in more than on line or note'''

            for property_match in key_value_property:
                key = property_match['key']
                key_span = [property_match.start('key') + carret_position, property_match.end('key') + carret_position]
                value = property_match['value']
                value_span = [property_match.start('value') + carret_position,
                              property_match.end('value') + carret_position]
                line_number_span = [
                    line_number_offset + get_line_number(properties_lines[:property_match.start('key')]) - 1,
                    line_number_offset + get_line_number(properties_lines[:property_match.end('value') - 1]) - 1]
                if DEBUG:
                    print(f'key  : _{key}_')
                    print(f'value: _{value}_')

                string_property = StringProperty.from_string(value)
                if string_property:
                    if DEBUG:
                        print('single string', value)
                        print(f'        |{string_property}| span: {value_span}, line: {line_number_offset}')

                    node.add_property(key, string_property, file_path, line_number_span, key_span, value_span)
                    continue

                string_list_property = StringListProperty.from_string(value)
                if string_list_property:
                    if DEBUG:
                        print('multi string')
                        for s in string_list_property:
                            print(f'        |{s}|')
                    node.add_property(key, string_list_property, file_path, line_number_span, key_span, value_span)
                    continue

                # cell = re.match(r'^<\s*((?:&?[\w]+\s*)+)>$', value) # this one causes catastrophic backtracking for, e.g., "<0x00010081 0x00000000 0x04000000 0x00000000 0x04000040 0x00000000>, <0>"
                # references:
                # https://javascript.info/regexp-catastrophic-backtracking
                # https://www.regular-expressions.info/catastrophic.html
                # my solution: according to https://javascript.info/regexp-catastrophic-backtracking#how-to-fix (great article. a little hard to understand backtracking btw :) )
                # cell = re.match(r'^<\s*(?:(?:&?[\w]+\s+)+&?[\w]+\s*)>$', value) # this one causes catastrophic backtracking for, e.g., "<0x00010081 0x00000000 0x04000000 0x00000000 0x04000040 0x00000000>, <0>"
                # simplifying:
                cell = CellProperty.from_string(value)

                if cell:
                    node.add_property(key, cell, file_path, line_number_span, key_span, value_span)
                    if DEBUG:
                        print('cell')
                        for e in cell:
                            print(f'        |{e}|')
                    continue

                alias = AliasProperty.from_string(value)
                if alias:
                    node.add_property(key, AliasProperty(value), file_path, line_number_span, key_span, value_span)
                    if DEBUG:
                        print('alias')
                        print(f'        |{alias}|')
                    continue

                # mixed_property = re.finditer(r'(?:(?P<cell><\s*(?:(?:\s*&)?\w+\s*)+>)|(?P<string>"(?:[^\n;"]*)"\s*)|(?P<string_list>(?:"[^\n;"]*"\s*,\s*?)+"[^\n;"]*")|(?P<binary>\[\s*(?:(?:(?:0[xX][\dA-Fa-f]+)|(?:\d+))\s*)+\]))', value)
                mixed_property = MixedProperty.from_string(value)
                if mixed_property:
                    node.add_property(key, mixed_property, file_path, line_number_span, key_span, value_span)
                    continue

                raise ValueError(f'''
                   If you got here, something if wrong or is not supported.
                   Current line number: {line_number_offset}
                   Current carret: {carret_position}
                   Current content: {property_match[0]}')
                   ''')

            empty_property: Iterator[re.Match[str]] = re.finditer(r'\n\s*(?P<property_name>[\w,.+?#\-]+);',
                                                                  properties_lines)
            '''it is an empty property (like wakeup-source)'''
            for property_match in empty_property:

                if DEBUG:
                    print(f'={property_match[0]}= EMPTY')

                property_name = property_match['property_name']
                property_span = [property_match.start('property_name') + carret_position,
                                 property_match.end('property_name') + carret_position]
                line_number_span = [
                    line_number_offset + get_line_number(properties_lines[:property_match.start('property_name')]) - 1,
                    line_number_offset + get_line_number(
                        properties_lines[:property_match.end('property_name') - 1]) - 1]
                node.add_property(property_name, EmptyProperty(), file_path, line_number_span, property_span,
                                  property_span)
    if DEBUG:
        for rn in root_nodes:
            print(RenderTree(rn))

    return root_nodes


if __name__ == "__main__":
    # parse_device_tree(Path("/home/grilo/linux-toradex/arch/arm/boot/dts/imx6qdl.dtsi"))
    file_list = find_in_dt(Path("/home/grilo/linux-toradex/arch/arm/boot/dts/imx6dl-colibri-eval-v3.dts"), '', search_in='all', returning='only_files')[1]
    file_root_nodes = {}
    for file in file_list:
        if file.suffix in ['.dtsi', '.dts']:
            file_root_nodes[file.name] = parse_device_tree(file)

    print('oi')