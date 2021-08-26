#reference: https://github.com/devicetree-org/devicetree-specification/releases ; v0.3
from pathlib import Path
from enum import Enum, auto

import re
import pprint

#from treelib import Tree, Node
from anytree import Node, RenderTree, NodeMixin, PreOrderIter

from typing import Union, List, Iterator, AnyStr

DEBUG = False

class Token:

    end = r';'

    #only outside of every node
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
    Comment = auto() # inside a comment (multiline or not)
    Node = auto() # inside a node
    RootNode = auto() # directly inside THE root node (maybe not useful?)
    IncludeLine = auto() # inside a include line
    IncludeFileName = auto() # inside a included file name (that should be inside a include line and could be surrounded by "double quotes" or <angle brackets>)
    String = auto() # inside a string ( "string" )
    PropertyLine = auto() # inside a property line (something = anything)
    Array = auto() # inside an array ( <one two three ... > )

class Regex:
    include_same_dir    = r'#include +"(?P<file_path>[^"]+?)"' # group 0: path and file name with extension
    include_default_dir = r'#include +<(?P<file_path>[^>]+?)>' # group 0: path and file name with extension

    valid_node_name = r'[\w,\.\+-]+'
    valid_property_name = r'[\w,\.\+\?#-]+'

    boring = r'^\s*$'

    root_node = r'/ {'

    node = f'(?P<name>{valid_node_name})(?:@(?P<value>{valid_node_name})) +{{'

    multiline_comment = r'/\*(?:[^/*][^*]*\*+)*/'
    '''inspired by https://stackoverflow.com/a/36328890/6609908'''




class StringProperty(str):
    '''string-property = "a string";'''
    pass

class StringListProperty(List[str]):
    '''string-list = "red fish", "blue fish";'''
    pass

class CellProperty(List[Union[int, str]]):
    '''cell-property = <0xbeef 123 0xabcd1234>;'''
    pass

class BinaryProperty(List[int]):
    '''binary-property = [0x01 0x23 0x45 0x67];'''
    pass

class EmptyProperty(str):
    '''wakeup-source;'''
    pass

class MixedProperty(List[Union[StringProperty, CellProperty, BinaryProperty]]):
    '''mixed-property = "a string", [0x01 0x23 0x45 0x67], <0x12345678>;'''
    def get_type_info(self):
        type_list = [type(element) for element in self]
        return type_list

NodePropertyValue = Union[StringProperty,
                          CellProperty,
                          BinaryProperty,
                          MixedProperty,
                          StringListProperty,
                          MixedProperty]

class ValueElement:
    def __init__(self, value:NodePropertyValue, file_path:Path, line_number:List[int], key_span:List[int], value_span:List[int]):
        self.value:NodePropertyValue = value
        self.file_path:Path = file_path
        self.line_number:List[int] = line_number
        self.single_line:bool = len(line_number) == 1
        self.key_span:List[int] = key_span
        self.value_span:List[int] = value_span


class DeviceTreeNodeProperty:

    def __init__(self, name:str, value:NodePropertyValue, file_path:Path, line_number:List[int], key_span:List[int], value_span:List[int]):
        self._name:str = name
        self._value:NodePropertyValue = value
        self._history_list:List = [ValueElement(self._value, file_path, line_number, key_span, value_span)]

    @property
    def name(self):
        return self._name

    @property
    def value(self):
        return self._value

    def set_value(self, value:NodePropertyValue, file_path:Path, line_number:List[int], key_span:List[int], value_span:List[int]):
        if isinstance(value, self.type):
            self._value = self._value
            self._history_list.append(ValueElement(self._value, file_path, line_number, key_span, value_span))
        else:
            raise TypeError(f'The property {self._name} was created as {self.type}, but the new value {value} is of type {type(value)}!')

    @property
    def type(self):
        return type(self._value)

    @property
    def history_list(self):
        return self._history_list

    def __repr__(self):
        return f'{self.name} - {repr(self.value)}'

# TODO: DeviceTree class? to register all phandles & nodes, all source files & nodes, ...

class DeviceTreeNode(NodeMixin):

    # TODO: remove the default file_path_source
    def __init__(self, name:str, is_overlay:bool=False, file_path_source:Path=Path(), phandle:str=None, at:Union[str,int]=None, parent=None, children=None):
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
            raise ValueError('An overlay can not have a phandle nor an at (@) value! (or can it?)\nFor an overlay node, the "&node_name" is its name! ')
        else:
            self._at = at
            self._phandle = phandle

        super(DeviceTreeNode, self).__init__()
        self._properties:dict = {}

        self.name:str = name
        self._is_overlay = is_overlay
        self._file_path_source = file_path_source
        self._properties_span = [-1, -1]
        self._node_span = [-1, -1]

        self.parent = parent
        self.children = [] if children == None else children

    def add_property(self, name:str, value:NodePropertyValue, file_source:Path,
                     line_number:List[int], key_span:List[int], value_span:List[int]) -> None:
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

    def modify_property(self, name:str, value:Union[str,None]) -> None:
        if not name in self._properties:
            raise KeyError(f'Property {name} can not be modified because it does not exist yet!')
        else:
            self._properties[name] = value

    def remove_property(self, name:str)-> None:
        if self._properties.get(name) == None:
            raise KeyError(f'Property {name} can not be modified because it does not exist!')
        else:
            self._properties.pop(name)

    # def set_phandle(self, phandle:str) -> None:
    #     if not self._phandle == None:
    #         raise ValueError(f'Node already has a phandle {self._phandle} !')
    #     else:
    #         self._phandle = phandle

    def get_phandle(self) -> Union[str, int]:
        return self._phandle

    def set_at(self, at:Union[str,int]) -> None:
        if not self._at == None:
            raise ValueError(f'Node already has an @ {self._at} !')
        else:
            self._at = at
    
    def get_at(self) -> Union[str, int]:
        return self._at

    def set_properties_span_start(self, span_start:int):
        self._properties_span[0] = span_start

    def set_properties_span_end(self, span_end:int):
        self._properties_span[1] = span_end

    def get_properties_span(self):
        return self._properties_span

    def set_node_span_start(self, span_start:int):
        self._node_span[0] = span_start

    def set_node_span_end(self, span_end:int):
        self._node_span[1] = span_end

    def get_node_span(self):
        return self._node_span

    def __repr__(self):
        string = self.name
        if not self._at == None:
            string = f'{string} @ {self._at}'
        if not self._phandle == None:
            string = f'{self._phandle} : {string}'
        if self._is_overlay:
            string = f'{string} - overlay'

        string = f'{string}\n\t<{self._properties_span[0]}, {self._properties_span[1]}>'
        properties_part = '\n\t'.join([f'{k} - {v}' for k,v in self._properties.items()])
        string = f'{string}\n\t{properties_part}'

        return string


def get_line_number(text_contents):
    if len(text_contents) == 0:
        return 0
    else:
        return 1+len(text_contents.split('\n'))

def parse_device_tree(file_path:Path) -> None:
    global DEBUG
    if not file_path.exists():
        raise FileExistsError(f"{file_path} does not exist!")

    if not file_path.is_file():
        raise FileExistsError(f"{file_path} is not a file!")

    with open(file_path, 'r') as f:
        contents = f.read()

    root_node:re.Match=re.search(Regex.root_node, contents)

    if root_node == None:
        raise ValueError(f'Root node ( / ) could not be found in {file_path}!')

    print(contents[root_node.span()[0]:root_node.span()[1]])

    # visualization
    # https://regexper.com/#%28%3F%3A%28%3F%3A%28%26%28%5B%5Cw%2C.%2B%5C-%2F%5D%2B%29%29%7C%28%28%3F%3A%28%5B%5Cw%2C.%2B%5C-%2F%5D%2B%29%20*%3A%20*%29%3F%28%5B%5Cw%2C.%2B%5C-%2F%5D%2B%29%28%3F%3A%40%28%5B%5Cw%2C.%2B%5C-%5D%2B%29%29%3F%29%29%20*%7B%29%7C%28%20*%7D%3B%29
    # device tree specification v0.3 (13/feb/2020): https://github.com/devicetree-org/devicetree-specification/releases/tag/v0.3
    # labels (phandles) : section 6.2 : [\w]+
    # node name : section 2.2.1 : [\w,.\+\-]+
    # unit-address : section 2.2.1 (same as nome name) : [\w,.\+\-]+
    node_scopes = re.finditer(r'((?:(&(?P<phandle_only>[\w]+))|((?:(?P<phandle>[\w,.+\-]+) *: *)?(?P<name>[\w,.+\-/]+)(?:@(?P<at>[\w,.+\-]+))?)) *{)|( *};)',contents)

    c=0
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
    t=0
    # for DEBUG

    math:re.Match
    '''for iteration over regexp matches in this file'''
    for match in node_scopes:
        if match[0][-1] == '{':
            '''here we have the start of a node'''
            node_count+=1

            # this is needed because of the pop below
            node_header = match.groupdict()
            if node_header['phandle_only'] == None:
                '''this not is not an overlay node'''
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
                #while contents[carret_position] == ' ' or contents[carret_position] == '\t' or contents[carret_position] == '\n':
                #    carret_position += 1
                #    if carret_position > len(contents):
                #        raise ValueError(f'Reached End Of File {file_path}!')
                current_node.set_properties_span_start(carret_position)
                if DEBUG:
                    if contents[current_node.get_properties_span()[0]] == '\n':
                        print(f'{current_node.name} : first property char is linefeed {node_count}')
                    else:
                        print(f'{current_node.name} : first property char is NOT linefeed: {contents[current_node.get_properties_span()[0]]} {node_count}')
                current_node.set_node_span_start(match.span()[1])

                if DEBUG:
                    print(f'{pre}{current_node.name} start')
                    t+=1
                    pre='.'*t
            else:
                '''here we have an overlay node'''
                if not current_node == None:
                    '''an overlay node can not not be inside any other node (or can it?)'''
                    raise KeyError(f'This {match[0]} node is only a phandle. Should this be inside a node ({current_node.name})? Is this allowable?')
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
                            print(f'{current_node.name} : first property char is NOT linefeed: {contents[current_node.get_properties_span()[0]]} {node_count}')


                    if DEBUG:
                        print(f'{pre}{current_node.name} start')
                        t+=1
                        pre='.'*t


        elif match[0] == '};' and match['name'] == None:
            if DEBUG:
                t-=1
                pre='.'*t
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
                print('/**/',contents[node.get_properties_span()[0]:node.get_properties_span()[1]],'/**/')

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
        node:DeviceTreeNode
        for node in PreOrderIter(root):
            '''node by node'''
            if DEBUG:
                print(f'==|{node.name}|==')

            properties_lines = contents[node.get_properties_span()[0]:node.get_properties_span()[1]] # getting online the properties
            # TODO: find a way to not lose the original position of each thing in the original file!!!

            carret_position = node.get_properties_span()[0]
            '''curernt carret position in our analysis'''

            # TODO: update this value with the line number of each property of each node (currently, it only stores the line number of the first property of the current node)
            line_number_offset = get_line_number(contents[:carret_position])
            '''curernt line number in our analysis'''

            DEBUG = True
            if DEBUG:
                w=20
                print(f'{line_number_offset:{w-10}} {node.name:{w}} {properties_lines[:10]:{w}}')
            DEBUG=False
            '''a big problem: some lengthy properties (like cell properties) usually are broken in several lines'''

            #properties_lines = re.sub(r'/\*[^*/]*\*/','', properties_lines) # removing multiline comments
            #properties_lines = re.sub(r'//[^\n]*','', properties_lines) # removing dingle line comments
            #properties_lines = re.sub(r'\n','', properties_lines) # removing linefeed (maybe it is not reeeally needed)

            '''problem in the line below: by splitting the string, we lose track of position in the whole file.
            I could manually keep track of it, but ain't nobody got time for this.
            by using only regexp, it is easier solved (go to branch properties-by-regexp)'''

            # device tree specification v0.3 (13/feb/2020): https://github.com/devicetree-org/devicetree-specification/releases/tag/v0.3
            # property names : section 2.2.4 : [\w,.+?#\-]+

            key_value_property:Iterator[re.Match[AnyStr]] = re.finditer(r'\n\s*(?P<key>[\w,.+?#\-]+)\s*=\s*(?P<value>[^;]+);', properties_lines)
            '''this a property like <key = value>, regardless of being spread in more than on line or note'''

            for property_match in key_value_property:
                key = property_match['key']
                key_span = [property_match.start('key')+carret_position, property_match.end('key')+carret_position]
                value = property_match['value']
                value_span = [property_match.start('value')+carret_position, property_match.end('value')+carret_position]
                # if DEBUG:
                #     print(f'key  : %{key}%')
                #     print(f'value: %{value}%')

                # TODO: this matches any property (empty or not, multi-line or not), except MIXED PROPERTIES!
                '''
                ^\s*(([\w\-]+)|([#\w\-,]+\s*=\s*(?:("[^"]*"(\s*,\s*"[^"]*")*?)|(<[^;]*>)|(&[^;]*))));
                '''

                string_property = re.match(r'^"([^\n;"]*)"$', value)
                if string_property:
                    if DEBUG:
                        print('single string', value)
                        print(f'        |{string_property.groups()[0]}| span: {value_span}, line: {line_number_offset}')

                    node.add_property(key, value, file_path, [line_number_offset], key_span, value_span)
                    continue

                string_list = re.match(r'^("[^\n;"]*"\s*,\s*?)+"[^\n;"]*"$', value)
                if string_list:
                    strings = re.findall(r'"([^\n;"]*)"', value)
                    node.add_property(key, StringProperty(strings), file_path, [line_number_offset], key_span, value_span)
                    if DEBUG:
                        print('multi string')
                        for s in strings:
                            print(f'        |{s}|')
                    continue

                # cell = re.match(r'^<\s*((?:&?[\w]+\s*)+)>$', value) # this one causes catastrophic backtracking for, e.g., "<0x00010081 0x00000000 0x04000000 0x00000000 0x04000040 0x00000000>, <0>"
                # references:
                # https://javascript.info/regexp-catastrophic-backtracking
                # https://www.regular-expressions.info/catastrophic.html
                # my solution: according to https://javascript.info/regexp-catastrophic-backtracking#how-to-fix (great article. a little hard to understand backtracking btw :) )
                # cell = re.match(r'^<\s*(?:(?:&?[\w]+\s+)+&?[\w]+\s*)>$', value) # this one causes catastrophic backtracking for, e.g., "<0x00010081 0x00000000 0x04000000 0x00000000 0x04000040 0x00000000>, <0>"
                # simplifying:
                cell = re.match(r'^<([^>]+)>\s*$', value)

                if cell:
                    # TODO: maybe remember (store somewhere) if an integer value was represented as hexa or as decimal?
                    elements = cell[1].split()
                    for i in range(len(elements)):
                        if elements[i][0:2] == '0x' or elements[i][0:2] == '0X':
                            elements[i] = int(elements[i], 16)
                        else:
                            try:
                                elements[i] = int(elements[i], 10)
                            except ValueError:
                                elements[i] = str(elements[i])
                            except:
                                raise ValueError(f'It is not an hexa int, dec int, nor str... WHAT IS THIS? Value: {elements[i]}')

                    node.add_property(key, CellProperty(elements), file_path, [line_number_offset], key_span, value_span)
                    if DEBUG:
                        print('cell')
                        for e in elements:
                            print(f'        |{e}|')
                    continue

                # TODO: grab the aliases
                alias = re.match(r'^(&[\w]+)$', value)
                if alias:
                    if DEBUG:
                        print('alias')
                        print(f'        |{alias.groups()[0]}|')
                    continue

                #mixed_property = re.finditer(r'(?:(?P<cell><\s*(?:(?:\s*&)?\w+\s*)+>)|(?P<string>"(?:[^\n;"]*)"\s*)|(?P<string_list>(?:"[^\n;"]*"\s*,\s*?)+"[^\n;"]*")|(?P<binary>\[\s*(?:(?:(?:0[xX][\dA-Fa-f]+)|(?:\d+))\s*)+\]))', value)
                mixed_property = re.finditer(r'(?:(?P<cell><\s*(?:(?:\s*&)?\w+\s*)+>)|(?P<string>"(?:[^\n;"]*)"\s*)|(?P<binary>\[\s*(?:(?:(?:0[xX][\dA-Fa-f]+)|(?:\d+))\s*)+\]))',
                                             value)
                if mixed_property:
                    auxMixedProperty:MixedProperty = MixedProperty()
                    current_property = None
                    for p in mixed_property:
                        if sum([0 if v==None else 1 for v in p.groupdict().values()]) > 1:
                            raise ValueError(f'More than one type (string and/or cell and/or binary) found: {[f"{k}: {v}" for k,v in p.groupdict().items() if not v == None]}')
                        elif not p['cell'] == None:
                            current_property = CellProperty([p['cell']])
                        elif not p['string'] == None:
                            current_property = StringProperty(p['string'])
                        elif not p['binary'] == None:
                            current_property = BinaryProperty(p['binary'])
                        else:
                            raise f"Something is wrong! None of cell, string or binary. What is this?? value: {p[0]}"

                        auxMixedProperty.append(current_property)

                    node.add_property(key, auxMixedProperty, file_path, [line_number_offset], key_span, value_span)
                    continue

                raise ValueError(f'''
                   If you got here, something if wrong or is not supported.
                   Current line number: {line_number_offset}
                   Current carret: {carret_position}
                   Current content: {property_match[0]}')
                   ''')
            DEBUG=False

            empty_property:Iterator[re.Match[str]] = re.finditer(r'\n\s*(?P<property>[\w,.+?#\-]+);', properties_lines)
            '''it is an empty property (like wakeup-source)'''
            for property_match in empty_property:
                if DEBUG:
                    print(f'={property_match[0]}= EMPTY')
                continue


    for rn in root_nodes:
        print(RenderTree(rn))

if __name__ == "__main__":
    # parse_device_tree(Path("/home/grilo/linux-toradex/arch/arm/boot/dts/imx6qdl.dtsi"))
    parse_device_tree(Path("/home/grilo/linux-toradex/arch/arm/boot/dts/imx6dl-colibri-eval-v3.dts"))
