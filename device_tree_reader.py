#reference: https://github.com/devicetree-org/devicetree-specification/releases ; v0.3
from pathlib import Path
from enum import Enum, auto

import re
import pprint

#from treelib import Tree, Node
from anytree import Node, RenderTree, NodeMixin, PreOrderIter

from typing import Union, List

DEBUG=False

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
    include_same_dir    = re.compile(r'#include +"(?P<file_path>[^"]+?)"') # group 0: path and file name with extension
    include_default_dir = re.compile(r'#include +<(?P<file_path>[^>]+?)>') # group 0: path and file name with extension
    
    valid_node_name = r'[\w,\.\+-]+'
    valid_property_name = r'[\w,\.\+\?#-]+'

    boring = re.compile(r'^\s*$')

    root_node = re.compile(r'/ {')

    node = re.compile(f'(?P<name>{valid_node_name})(?:@(?P<value>{valid_node_name})) +{{')
    
    
class DeviceTreeNode(NodeMixin):

    StringProperty = str
    '''string-property = "a string";'''
    CellProperty = List[int]
    '''cell-property = <0xbeef 123 0xabcd1234>;'''
    BinaryProperty = List[int]
    '''binary-property = [0x01 0x23 0x45 0x67];'''
    MixedProperty = List[Union[StringProperty, BinaryProperty, CellProperty]] # not supported
    '''mixed-property = "a string", [0x01 0x23 0x45 0x67], <0x12345678>;'''
    StringListProperty = List[str]
    '''string-list = "red fish", "blue fish";'''
    EmptyProperty = bool
    '''wakeup-source;'''

    #TODO: remove the default file_path_source
    def __init__(self, name:str, is_overlay:bool=False, file_path_source:Path=Path(), phandle:str=None, at:Union[str,int]=None, parent=None, children=None):
        if is_overlay and (phandle or at):
            raise ValueError('An overlay can not have a phandle nor an at (@) value! (or can it?)')
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

    def add_property(self, name:str, value:Union[StringProperty,CellProperty, BinaryProperty, MixedProperty, StringListProperty]) -> None:
        if name in self._properties.keys():
            raise KeyError(f'Property {name} already exist!')
        else:
            self._properties[name] = value

    def modify_property(self, name:str, value:Union[str,None]) -> None:
        if not name in self._properties.keys():
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

        string = f'{string} - {self._properties}'
        string = f'{string} - <{self._properties_span[0]}, {self._properties_span[1]}>'

        return string

def get_line_number(text_contents):
    return len(text_contents.split('\n'))

def parse_device_tree(file_path:Path) -> None:
    if not file_path.exists():
        raise FileExistsError(f"{file_path} does not exist!")

    if not file_path.is_file():
        raise FileExistsError(f"{file_path} is not a file!")

    with open(file_path, 'r') as f:
        contents = f.read()
    
    root_node:re.Match=Regex.root_node.search(contents)

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
                while contents[carret_position] == ' ' or contents[carret_position] == '\t' or contents[carret_position] == '\n':
                    carret_position += 1
                    if carret_position > len(contents):
                        raise ValueError(f'Reached End Of File {file_path}!')
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
                    while contents[carret_position] == ' ' or contents[carret_position] == '\t' or contents[carret_position] == '\n':
                        carret_position += 1
                        if carret_position > len(contents):
                            raise ValueError(f'Reached End Of File {file_path}!')
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


        elif match[0] == '};' and match.groupdict()['name'] == None:
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
        node:DeviceTreeNode
        for node in PreOrderIter(root):

            if DEBUG:
                print(f'==|{node.name}|==')

            # TODO: find a way to not lose the original position of each thing in the original file!!!
            index_first_char = get_line_number(contents[:node.get_properties_span()[0]])
            w=20
            print(f'{index_first_char:{w-10}} {node.name:{w}} {contents[node.get_properties_span()[0]:node.get_properties_span()[0]+10]:{w}}')
            properties_lines = contents[node.get_properties_span()[0]:node.get_properties_span()[1]] # getting online the properties
            properties_lines = re.sub(r'/\*[^*/]*\*/','', properties_lines) # removing multiline comments
            properties_lines = re.sub(r'//[^\n]*','', properties_lines) # removing dingle line comments
            properties_lines = re.sub(r'\n','', properties_lines) # removing linefeed (maybe it is not reeeally needed)
            properties_lines = [p.strip() for p in properties_lines.split(";")] # splitting by the end of statements (? expressions ?)
            properties_lines = [p for p in properties_lines if len(p) > 0] # removing 0-length strings

            for line in properties_lines:
                if len(line) == 0:
                    '''not considering 0-length strings'''
                    raise ValueError('We are still getting 0-length strings...')
                    continue
                else:
                    if '=' in line:
                        '''it is a line with a key = value'''
                        key, value = [e.strip() for e in line.split('=')]
                        #print(f'|{key}| -- |{value}| -- ', end='')
                        if DEBUG:
                            print(f'    |{key}| -- ', end='')
                        string_property = re.match(r'^"([^\n;"]*)"$', value)
                        if string_property:
                            if DEBUG:
                                print('single string')
                                print(f'        |{string_property.groups()[0]}|')
                            node.add_property(key, value)
                            continue

                        string_list = re.match(r'^("[^\n;"]*"\s*,\s*?)+"[^\n;"]*"$', value)
                        if string_list:
                            strings = re.findall(r'"([^\n;"]*)"', value)
                            node.add_property(key, list(strings))
                            if DEBUG:
                                print('multi string')
                                for s in strings:
                                    print(f'        |{s.groups()[0]}|')
                            continue

                        cell = re.match(r'^<((?:&?[\w]+\s*)+)>$', value)
                        if cell:
                            elements = cell.groups()[0].split()
                            if DEBUG:
                                print('cell')
                                for e in elements:
                                    print(f'        |{e}|')
                            continue

                        alias = re.match(r'^(&[\w]+)$', value)
                        if alias:
                            if DEBUG:
                                print('alias')
                                print(f'        |{alias.groups()[0]}|')

                    else:
                        '''this line is just a binary-property (like wakeup-source or interrupt-controller)'''
                        binary_property = re.match(r'^\[(?:\s*([a-fA-F0-9xX]+)\s*)+\]$', value)
                        if binary_property:
                            elements = re.finditer(r'([a-fA-F0-9xX]+)', value)
                            if DEBUG:
                                print('array')
                                for e in elements:
                                    print(f'        |{e.groups()[0]}|')
                            continue


if __name__ == "__main__":
    # parse_device_tree(Path("/home/grilo/linux-toradex/arch/arm/boot/dts/imx6qdl.dtsi"))
    parse_device_tree(Path("/home/grilo/linux-toradex/arch/arm/boot/dts/imx6dl-colibri-eval-v3.dts"))
