module dff(CK,reset,Q,D);
   input CK;
   input reset;
   input D;
   output reg Q;

   always @(posedge CK, posedge reset)
     begin
	if (reset)
	  begin
	     Q <= 0;
	  end
	else
	  begin
	     Q <= D;
	  end
     end
   
endmodule
