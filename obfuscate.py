import argparse
from pathlib import Path

import random
import networkx as nx

import matplotlib.pyplot as plt

from pyverilog.vparser.parser import parse as vparser 
import pyverilog.vparser.ast as vast

from pyverilog.dataflow.modulevisitor import ModuleVisitor
from pyverilog.dataflow.signalvisitor import SignalVisitor
from pyverilog.ast_code_generator.codegen import ASTCodeGenerator
from pyverilog.utils.signaltype import isInput


# def get_io_signals(ast, top_module_name):
#     '''Get the IO port signals information

#     '''
#     module_visitor = ModuleVisitor()
#     module_visitor.visit(ast)
#     module_names = module_visitor.get_modulenames()
    
#     if (top_module_name not in module_names):
#         raise Exception("Top module {} not found.".format(top_module_name))

#     module_infotable = module_visitor.get_moduleinfotable()
#     io_signal_dict = dict(module_infotable.getSignals(top_module_name))
    
#     return io_signal_dict


def construct_obfuscation_graph(key_length, ip_width):

    Graph = nx.DiGraph()
    key = dict()
    pos = dict()

    # Form edges with a random value as a key item at
    # every edge.
    for i in range(key_length):
        key_item = random.randint(1, ip_width)
        Graph.add_edge(i, i+1, object=key_item)
        key[(i, i+1)] = key_item


    pos = nx.circular_layout(Graph)    
    nx.draw(Graph, pos, with_labels=True)
    nx.draw_networkx_edge_labels(Graph, pos, edge_labels = key)
    plt.savefig("obfuscation-fsm.png")

    return Graph


def _get_verilog_from_transitions(obfuscation_graph, key_length, ip_width, invert_vec_length):
    toret  = ""
    adjacency = dict(obfuscation_graph.adjacency())
    print(adjacency)
    
    for node_idx in adjacency:
        toret += "\n".join([
            "          {}: begin".format(node_idx),
            "             case (ip_vec)\n",
            ])

        for dest in adjacency[node_idx]:
            toret += "\n".join([
                "               {}: begin".format(adjacency[node_idx][dest]['object']),
                "                  next_state = {};".format(dest),
                "               end\n",
                ])

        toret += "\n".join([
            "               default: begin",
            "                  next_state = 0;",
            "               end",
            "             endcase",
            "          end\n",
            ])
        
    return toret


def construct_obfuscation_fsm(obfuscation_graph, key_length, ip_width, invert_vec_length):

    module_header = "\n".join(["module obfuscation_fsm (",
                               "            input wire          clk,",
                               "            input wire          reset,",
                               "            input wire [{}-1:0]  ip_vec,".format(ip_width),
                               "            output wire [{}-1:0] op_vec,".format(invert_vec_length),
                               "            output reg          reset_orig_fsm",
                               "            );",
                               "",
                               "   reg [{}-1:0]                    state, next_state;".format((key_length-1).bit_length()),
                               "",
                               "",
                               ])


    module_body = "\n".join(["   always @(posedge clk)\n",
                             "     begin",
                             "       if (reset)",
                             "         begin",
                             "           state <= 0;",
                             "         end",
                             "       else",
                             "         begin",
                             "           state <= next_state;",
                             "         end",
                             "     end",
                             "",
                             "",
                             "   always @(posedge clk)",
                             "     begin",
                             "       case(state)",

                             _get_verilog_from_transitions(obfuscation_graph, key_length, ip_width, invert_vec_length),

                             "       endcase",
                             "     end",
                             "",
                             "\n"
                            ])

    
    module_footer = "endmodule\n"
    module = module_header + module_body + module_footer

    with open("obfuscation_fsm.v", "w") as f:
        f.write(module)
    
    return module
    

    

def main(args):
    # # Parse and get the AST of the netlist
    # ast, directives = vparser([str(args.netlist_file)])

    # # Get the IO ports of the netlist
    # io_signals_dict = [i for i in get_io_signals(ast, args.top_module)]

    # Construct obfuscation FSM
    obfuscation_graph   = construct_obfuscation_graph(args.key_length, 5)
    obfuscation_fsm_str = construct_obfuscation_fsm(obfuscation_graph, args.key_length, 5, args.invert_vec_length)


if (__name__ == "__main__"):
    
    parser = argparse.ArgumentParser(description = "Command line arguments for the HARPOON tool.")

    parser.add_argument("-f", "--netlist_file",
                        required = True,
                        type = Path,
                        help = "Input netlist file.")

    parser.add_argument("-t", "--top_module",
                        required = True,
                        type = str,
                        help = "Top module name.")

    parser.add_argument("-k", "--key_length",
                        default = 5,
                        type = int,
                        help = "Length of authentication key.")

    parser.add_argument("-i", "--invert_vec_length",
                        default = 5,
                        type = int,
                        help = "Length of inverting vector.")

    
    args = parser.parse_args()

    main(args)
