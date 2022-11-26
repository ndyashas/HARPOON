import argparse
from pathlib import Path

import os
import random
import networkx as nx

import circuitgraph as cg

import matplotlib.pyplot as plt

def preprocess_file(netlist_file, top_module, invert_vec_length):

    os.system("rm -rf generated; mkdir -p generated; cp {} generated/orig_copy.v".format(netlist_file))

    # Comment out the 'dff' module
    verilog_lines = []
    with open("generated/orig_copy.v", "r") as orig:
        orig_verilog_lines = orig.readlines()

    modified_verilog_lines = []
    flag = False
    for line in orig_verilog_lines:
        if ((flag) or (("module" in line) and ("dff" in line))):
            flag = True
            line = "// " + line

        if ("endmodule" in line):
            flag = False
            
        modified_verilog_lines.append(line)
            
    with open("generated/orig_copy.v", "w") as modified:
        modified.writelines(modified_verilog_lines)
        # modified.write("\n\nmodule dff(CK,Q,D);\n")
        # modified.write("input CK, D;\n")
        # modified.write("output Q;\n")
        # modified.write("endmodule\n")

    os.system("./utils/preprocess.sh generated/orig_copy.v > generated/orig_replace_ffx.v")

        
    # circuit graph
    dff_bb = cg.BlackBox("dff", ["reset", "CK", "D"], ["Q"])    
    ck = cg.from_file("generated/orig_replace_ffx.v", blackboxes = [dff_bb])

    primitive_gates = [
        "and",
        "or",
        "xor",
        "not",
        "nand",
        "nor",
        "xnor",
    ]

    original_inputs = ck.filter_type("input")
    original_outputs = ck.outputs()
    original_internal_nodes = [node for node in ck.filter_type(primitive_gates) if not ck.is_output(node)]
    number_of_nodes = len(original_internal_nodes)

    randomly_sampled_nodes = random.sample(list(original_internal_nodes), invert_vec_length)
    
    for node in randomly_sampled_nodes:
        print(node, ck.type(node))

        ck.add(node + "_flipper", "input")
        
        # Construct a duplicate of the current node
        ck.add(node + "_orig", ck.type(node), fanin=ck.fanin(node))

        # Disconnect all parents feeding into this
        ck.disconnect(ck.fanin(node), node)
        # ck.set_type(node, "buf")

        # Add an 'XOR' gate
        fanouts_of_node = ck.fanout(node)
        ck.remove(node)
        ck.add(node + "_flipped", "xor", fanin={node + "_orig", node + "_flipper"}, fanout = fanouts_of_node)



    ck.add("reset", node_type="input", fanout = ["DFF_RESET"])

    cg.to_file(ck, "generated/orig_ffx_2_dffsr.v")
    
    return randomly_sampled_nodes, original_inputs, original_outputs



    
def get_io_signals(ast, top_module_name):
    '''Get the IO port signals information

    '''
    module_visitor = ModuleVisitor()
    module_visitor.visit(ast)
    module_names = module_visitor.get_modulenames()
    
    if (top_module_name not in module_names):
        raise Exception("Top module {} not found.".format(top_module_name))

    
    module_infotable = module_visitor.get_moduleinfotable()

    io_signal_dict = dict(module_infotable.getDefinitions())
    variables = module_infotable.getVariables()

    print(io_signal_dict[top_module_name].getIOPorts())
    
    return io_signal_dict

    
    

def construct_obfuscation_graph(key_length, ip_width):

    Graph = nx.DiGraph()
    key = dict()
    wrong_transitions = dict()
    additional_non_key_nodes = []

    node_color = []
    
    # Construct the obfuscation FSM
    with open("generated/key.txt", "w") as f:
        for i in range(key_length):
            key_item = random.randint(1, ip_width)
            Graph.add_edge(i, i+1, object=key_item)
            node_color.append("#4CD4EF")
            key[(i, i+1)] = key_item
            f.write(str(key_item)+"\n")

    # Yay! authenticated successfully. Stay in the same state!
    Graph.add_edge(i+1, i+1, object='default')
    key[(i+1, i+1)] = 'default'
    
    first_state = 0
    # The actual last state is 'valid' initialization state
    # Thus, we must loop only in the states before that.
    last_state  = key_length - 1

    # Add some additional FSM states to make the
    # adversary stay in the obfuscated FSM
    node_idx = key_length + 1
    Graph.add_edge(last_state, node_idx, object='default')
    wrong_transitions[(last_state, node_idx)] = 'default'
    additional_non_key_nodes.append(node_idx)
    node_color.append("#EE8787")

    for i in range(random.randint(int(key_length/2), key_length)):
        Graph.add_edge(node_idx, node_idx+1, object='default')
        node_color.append("#EE8787")
        wrong_transitions[(node_idx, node_idx+1)] = 'default'
        node_idx += 1
        additional_non_key_nodes.append(node_idx)

    # Final transition back to node 0
    Graph.add_edge(node_idx, 0, object='default')
    wrong_transitions[(node_idx, 0)] = 'default'
    node_color.append("#EE8787")


    # Random edges from each node back to
    # No need for a random transition for last obfuscated state
    # node.
    for i in range(key_length-1):
        randomly_picked_node = random.choice(additional_non_key_nodes)
        Graph.add_edge(i, randomly_picked_node, object = 'default')
        wrong_transitions[(i, randomly_picked_node)] = 'default'


    pos = nx.circular_layout(Graph)    
    nx.draw(Graph, pos, with_labels=True)

    edge_labels = dict()
    for k in key:
        edge_labels[k] = key[k]

    for k in wrong_transitions:
        edge_labels[k] = wrong_transitions[k]

    node_color[key_length] = "#4CEF57"
    
    nx.draw(Graph, pos, node_color = node_color)
    nx.draw_networkx_edge_labels(Graph, pos, edge_labels = edge_labels)
    plt.savefig("generated/obfuscation-fsm.png")            

    return Graph


def _get_verilog_from_transitions(obfuscation_graph, key_length, ip_width, invert_vec_length):
    toret  = ""
    adjacency = dict(obfuscation_graph.adjacency())
    
    for node_idx in adjacency:
        toret += "\n".join([
            "             {}: begin".format(node_idx),
            "                case (ip_vec)\n",
            ])

        for dest in adjacency[node_idx]:
            op_vec_val = random.randint(2**(invert_vec_length-1), 2**invert_vec_length-1)
            reset_orig_fsm = 0;
            if (dest == node_idx):
                op_vec_val = 0;
                reset_orig_fsm = 1;

                toret += "\n".join([
                    "                  {}: begin".format(adjacency[node_idx][dest]['object']),
                    "                     state <= {};".format(dest),
                    "                     if (!reset_flag)",
                    "                       begin",
                    "                          reset_orig_fsm <= 1;",
                    "                          reset_flag <= 1;",
                    "                       end",
                    "                     else",
                    "                       begin",
                    "                          reset_orig_fsm <= 0;",
                    "                       end",
                    "                     op_vec <= {};".format(op_vec_val),
                    "                  end\n",
                ])

            else:
                toret += "\n".join([
                    "                  {}: begin".format(adjacency[node_idx][dest]['object']),
                    "                     state <= {};".format(dest),
                    "                     reset_orig_fsm <= 0;",
                    "                     op_vec <= {};".format(op_vec_val),
                    "                  end\n",
                ])

        toret += "\n".join([
            "                endcase",
            "             end\n",
            ])
        
    return toret


def construct_obfuscation_fsm(obfuscation_graph, key_length, ip_width, invert_vec_length):

    module_header = "\n".join(["module obfuscation_fsm (",
                               "            input wire          clk,",
                               "            input wire          reset,",
                               "            input wire [{}-1:0]  ip_vec,".format(ip_width),
                               "            output reg  [{}-1:0] op_vec,".format(invert_vec_length),
                               "            output reg          reset_orig_fsm",
                               "            );",
                               "",
                               "   reg [{}:0]                    state;".format((key_length-1).bit_length()),
                               "   reg                             reset_flag;",
                               "",
                               "",
                               ])


    module_body = "\n".join(["   always @(posedge clk)",
                             "     begin",
                             "       if (reset)",
                             "         begin",
                             "           state <= 0;",
                             "           reset_orig_fsm <= 0;",
                             "           reset_flag <= 0;",
                             "           op_vec <= {};".format(random.randint(2**(invert_vec_length-1), 2**invert_vec_length-1)),
                             "         end",
                             "       else",
                             "         begin",
                             "           case(state)",

                             _get_verilog_from_transitions(obfuscation_graph, key_length, ip_width, invert_vec_length),

                             "           endcase",
                             "         end",
                             "     end"
                             "",
                             "\n"
                            ])

    
    module_footer = "endmodule\n"
    module = module_header + module_body + module_footer

    with open("generated/obfuscation_fsm.v", "w") as f:
        f.write(module)

    return module
    
# TODO put outputs too
def merge(top_module, randomly_sampled_nodes, original_inputs, original_outputs):
    module_header  = "module top_module (\n           "
    module_header += ",\n           ".join(original_inputs) + ",\n           "
    module_header += ",\n           ".join(original_outputs) + ",\n           "
    module_header += "reset);\n\n"


    module_body     = "   " + ";\n   ".join(["input {}".format(original_input) for original_input in original_inputs]) + ";\n"
    module_body    += "   input reset;\n"
    module_body    += "   " + ";\n   ".join(["output {}".format(original_output) for original_output in original_outputs]) + ";\n"
    module_body    += "   " + ";\n   ".join(["wire reset_orig_fsm", "wire [{}-1:0] op_vec".format(len(randomly_sampled_nodes))]) + ";\n"
    
    
    module_body    += "\n".join([
        "",
        "",
        "   obfuscation_fsm obfuscation_fsm_inst(",
        "                                        .clk(CK),",
        "                                        .reset(reset),",
        "                                        .ip_vec({" + ",".join([ip for ip in sorted(original_inputs) if ip != "CK"]) + "}),",
        "                                        .op_vec(op_vec),",
        "                                        .reset_orig_fsm(reset_orig_fsm));",
        "",
        "",
        "   {0} {0}_inst (".format(top_module),
        "         " + ",\n         ".join([".{0}({0})".format(original_input) for original_input in sorted(original_inputs)]) + ",",
        "         .reset(reset_orig_fsm),",
        "         " + ",\n         ".join([".{}_flipper(op_vec[{}])".format(sample_node, i) for i,sample_node in enumerate(randomly_sampled_nodes)]) + ",",

        "         " + ",\n         ".join([".{0}({0})".format(original_output) for original_output in original_outputs]) + ");",
        "",
        "",
    ])
    
    module_footer = "endmodule\n"

    module = module_header + module_body + module_footer

    
    
    with open("generated/top_module.v", "w") as f:
        f.write(module)
    
    return module

    
def synthesize_design():
    os.system("./utils/postprocess.sh")
    

def main(args):
    # Pre-process file
    randomly_sampled_nodes, original_inputs, original_outputs = preprocess_file(str(args.netlist_file), args.top_module, int(args.invert_vec_length))

    # Construct obfuscation FSM
    obfuscation_graph   = construct_obfuscation_graph(args.key_length, len(original_inputs)-1)
    obfuscation_fsm_str = construct_obfuscation_fsm(obfuscation_graph, args.key_length, len(original_inputs)-1, len(randomly_sampled_nodes))

    merge(args.top_module, randomly_sampled_nodes, original_inputs, original_outputs)

    synthesize_design()
    

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
